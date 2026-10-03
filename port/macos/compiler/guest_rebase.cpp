/* Experimental LLVM 22 pass for the macOS ARM guest.
 * Keep ILP32 layouts; dereferences use 64-bit address space 272 and a 1-TB
 * virtual address bias. Run after IR optimization and before code generation.
 * This is an ABI adapter, not a sandbox for untrusted code.
 */
#include "llvm/IR/IRBuilder.h"
#include "llvm/IR/IntrinsicInst.h"
#include "llvm/IR/InlineAsm.h"
#include "llvm/Passes/PassBuilder.h"
#include "llvm/Plugins/PassPlugin.h"
#include "llvm/Transforms/Utils/LowerMemIntrinsics.h"
using namespace llvm;
namespace {
constexpr uint64_t GuestBias = 0x10000000000ULL;
// Pointer-typed opaque integers must not acquire a memory address bias.
bool isHandle(StringRef name, unsigned argument) {
    return (argument == 0 &&
            (name == "hostposix_directory_next" || name == "hostposix_directory_close")) ||
           (argument == 3 &&
            (name == "hostgl_glDrawElements" || name == "hostgl_glDrawElementsInstanced")) ||
           (argument == 5 &&
            (name == "hostgl_glVertexAttribPointer" || name == "hostgl_glDrawRangeElements")) ||
           (argument == 4 && name == "hostgl_glVertexAttribIPointer");
}
struct RebasePass : PassInfoMixin<RebasePass> {
    bool ios = false;
    bool macCheck = false;
    explicit RebasePass(bool ios = false, bool macCheck = false) : ios(ios), macCheck(macCheck) {}
    PreservedAnalyses run(Module &module, ModuleAnalysisManager &) {
        const uint64_t bias = ios && !macCheck ? 0x400000000ULL : GuestBias;
        if (module.getDataLayout().getPointerSize(0) != 4 ||
            module.getDataLayout().getPointerSize(272) != 8)
            report_fatal_error("Halo rebase requires arm64_32 with 64-bit address space 272");
        DenseMap<Function *, Function *> hostFunctions;
        SmallVector<Function *, 128> declarations;
        for (Function &function : module)
            if (function.isDeclaration() && function.getName().starts_with("host"))
                declarations.push_back(&function);
        for (Function *old : declarations) {
            SmallVector<Type *, 16> parameters;
            StringRef name = old->getName();
            unsigned index = 0;
            for (Type *type : old->getFunctionType()->params()) {
                parameters.push_back(type->isPointerTy() && !isHandle(name, index)
                                         ? PointerType::get(module.getContext(), 272)
                                         : type);
                ++index;
            }
            std::string originalName = name.str();
            old->setName(originalName + ".guest_decl");
            Function *host = Function::Create(
                FunctionType::get(old->getReturnType(), parameters, old->isVarArg()),
                old->getLinkage(), originalName, module);
            hostFunctions[old] = host;
        }
        for (Function &function : module) {
            if (ios) {
                SmallVector<IntrinsicInst *, 8> tls;
                for (BasicBlock &block : function)
                    for (Instruction &instruction : block)
                        if (auto *intrinsic = dyn_cast<IntrinsicInst>(&instruction);
                            intrinsic && intrinsic->getIntrinsicID() == Intrinsic::threadlocal_address)
                            tls.push_back(intrinsic);
                for (auto *intrinsic : tls) {
                    auto *global = cast<GlobalVariable>(intrinsic->getArgOperand(0));
                    auto *control = module.getNamedGlobal(("__emutls_v." + global->getName()).str());
                    if (!control) report_fatal_error("Run lower-emutls with -emulated-tls before Halo iOS rebasing");
                    IRBuilder<> builder(intrinsic);
                    auto function = module.getOrInsertFunction("__emutls_get_address",
                        FunctionType::get(intrinsic->getType(), {control->getType()}, false));
                    intrinsic->replaceAllUsesWith(builder.CreateCall(function, {control}));
                    intrinsic->eraseFromParent();
                }
            }
            SmallVector<MemSetPatternInst *, 8> patterns;
            for (BasicBlock &block : function)
                for (Instruction &instruction : block)
                    if (auto *pattern = dyn_cast<MemSetPatternInst>(&instruction))
                        patterns.push_back(pattern);
            for (auto *pattern : patterns) {
                expandMemSetPatternAsLoop(pattern);
                pattern->eraseFromParent();
            }
            SmallVector<Instruction *, 64> work;
            for (BasicBlock &block : function)
                for (Instruction &instruction : block)
                    work.push_back(&instruction);
            for (Instruction *instruction : work) {
                IRBuilder<> builder(instruction);
                if (ios) {
                    // The signed code image can slide independently of guest data.
                    // Materialize ELF link addresses, never truncated native PCs.
                    // ELF relocation syntax is emitted by llc and assembled by
                    // the existing Darwin-to-ELF assembly adapter.
                    auto materialize = [&](auto &&self, Value *value) -> Value * {
                        if (auto *global = dyn_cast<GlobalValue>(value)) {
                            auto *literal = InlineAsm::get(
                                FunctionType::get(builder.getInt32Ty(), {global->getType()}, false),
                                "movz ${0:w}, #:abs_g0_nc:${1:c}\n\tmovk ${0:w}, #:abs_g1_nc:${1:c}",
                                "=r,i", false);
                            return builder.CreateIntToPtr(builder.CreateCall(literal, {global}), global->getType());
                        }
                        if (auto *expression = dyn_cast<ConstantExpr>(value)) {
                            Instruction *expanded = expression->getAsInstruction();
                            for (unsigned i = 0; i < expanded->getNumOperands(); i++)
                                expanded->setOperand(i, self(self, expanded->getOperand(i)));
                            builder.Insert(expanded);
                            return expanded;
                        }
                        return value;
                    };
                    DenseMap<std::pair<BasicBlock *, Value *>, Value *> incomingValues;
                    for (Use &operand : instruction->operands()) {
                        auto *call = dyn_cast<CallBase>(instruction);
                        if (call && &operand == &call->getCalledOperandUse() && call->getCalledFunction())
                            continue;
                        if (auto *phi = dyn_cast<PHINode>(instruction)) {
                            BasicBlock *incoming = phi->getIncomingBlock(operand.getOperandNo());
                            builder.SetInsertPoint(incoming->getTerminator());
                            // A switch can contribute several edges from one
                            // predecessor. LLVM requires identical SSA values
                            // on those edges, not separate equivalent copies.
                            auto key = std::make_pair(incoming, operand.get());
                            auto found = incomingValues.find(key);
                            if (found == incomingValues.end())
                                found = incomingValues.insert({key, materialize(materialize, operand.get())}).first;
                            operand.set(found->second);
                        } else {
                            operand.set(materialize(materialize, operand.get()));
                        }
                    }
                    builder.SetInsertPoint(instruction);
                }
                auto rebase = [&](Value *pointer, bool nullable = false) -> Value * {
                    Value *offset = builder.CreatePtrToInt(pointer, builder.getInt32Ty());
                    Value *wide = builder.CreateZExt(offset, builder.getInt64Ty());
                    // arm64_32 codegen assumes pointer registers have zero upper
                    // bits. Our real stack/global addresses can already contain
                    // the arena bias. In particular, splitting an unaligned i64
                    // load can fold OR(bias)+4 into base+(bias+4), adding it twice.
                    // Make the machine-level truncation explicit, opaque to that
                    // combine. Constants already have canonical upper bits.
                    if (!isa<Constant>(wide)) {
                        auto *truncate = InlineAsm::get(
                            FunctionType::get(builder.getInt64Ty(), {builder.getInt64Ty()}, false),
                            "and $0, $1, #0xffffffff", "=r,r", false);
                        wide = builder.CreateCall(truncate, {wide});
                    }
                    Value *address =
                        builder.CreateOr(wide, builder.getInt64(bias));
                    if (nullable)
                        address =
                            builder.CreateSelect(builder.CreateICmpEQ(offset, builder.getInt32(0)),
                                                 builder.getInt64(0), address);
                    return builder.CreateIntToPtr(address,
                                                  PointerType::get(module.getContext(), 272));
                };
                if (auto *va = dyn_cast<VAArgInst>(instruction)) {
                    Type *pointer = PointerType::get(module.getContext(), 0);
                    Value *list = rebase(va->getPointerOperand());
                    Value *cursor = builder.CreatePtrToInt(builder.CreateLoad(pointer, list),
                                                           builder.getInt32Ty());
                    unsigned alignment =
                        module.getDataLayout().getABITypeAlign(va->getType()).value();
                    uint64_t size = module.getDataLayout().getTypeAllocSize(va->getType());
                    if (alignment > 4)
                        cursor = builder.CreateAnd(
                            builder.CreateAdd(cursor, builder.getInt32(alignment - 1)),
                            builder.getInt32(~(alignment - 1)));
                    Value *value = builder.CreateLoad(
                        va->getType(), rebase(builder.CreateIntToPtr(cursor, pointer)));
                    Value *next = builder.CreateIntToPtr(
                        builder.CreateAdd(cursor, builder.getInt32((size + 3) & ~3u)), pointer);
                    builder.CreateStore(next, list);
                    va->replaceAllUsesWith(value);
                    va->eraseFromParent();
                } else if (auto *intrinsic = dyn_cast<IntrinsicInst>(instruction);
                           intrinsic && (intrinsic->getIntrinsicID() == Intrinsic::vacopy ||
                                         intrinsic->getIntrinsicID() == Intrinsic::vastart ||
                                         intrinsic->getIntrinsicID() == Intrinsic::vaend ||
                                         intrinsic->getIntrinsicID() == Intrinsic::stackrestore)) {
                    if (intrinsic->getIntrinsicID() == Intrinsic::vacopy) {
                        Value *value = builder.CreateLoad(PointerType::get(module.getContext(), 0),
                                                          rebase(intrinsic->getArgOperand(1)));
                        builder.CreateStore(value, rebase(intrinsic->getArgOperand(0)));
                    } else if (intrinsic->getIntrinsicID() == Intrinsic::vastart) {
                        auto fn = Intrinsic::getOrInsertDeclaration(
                            &module, Intrinsic::vastart,
                            {PointerType::get(module.getContext(), 272)});
                        builder.CreateCall(fn, {rebase(intrinsic->getArgOperand(0))});
                    }
                    if (intrinsic->getIntrinsicID() == Intrinsic::stackrestore) {
                        auto fn = Intrinsic::getOrInsertDeclaration(
                            &module, Intrinsic::stackrestore,
                            {PointerType::get(module.getContext(), 272)});
                        builder.CreateCall(fn, {rebase(intrinsic->getArgOperand(0))});
                    }
                    intrinsic->eraseFromParent();
                } else if (auto *load = dyn_cast<LoadInst>(instruction))
                    load->setOperand(0, rebase(load->getPointerOperand()));
                else if (auto *store = dyn_cast<StoreInst>(instruction))
                    store->setOperand(1, rebase(store->getPointerOperand()));
                else if (auto *atomic = dyn_cast<AtomicRMWInst>(instruction))
                    atomic->setOperand(0, rebase(atomic->getPointerOperand()));
                else if (auto *atomic = dyn_cast<AtomicCmpXchgInst>(instruction))
                    atomic->setOperand(0, rebase(atomic->getPointerOperand()));
                else if (auto *transfer = dyn_cast<MemTransferInst>(instruction)) {
                    // The target cannot lower AS272 libcalls. Call the rebased guest libc
                    // using its original ILP32 arguments instead.
                    Type *pointer = PointerType::get(module.getContext(), 0);
                    auto callee = module.getOrInsertFunction(
                        isa<MemMoveInst>(transfer) ? "memmove" : "memcpy",
                        FunctionType::get(pointer, {pointer, pointer, builder.getInt32Ty()},
                                          false));
                    builder.CreateCall(callee, {transfer->getRawDest(), transfer->getRawSource(),
                                                builder.CreateZExtOrTrunc(transfer->getLength(),
                                                                          builder.getInt32Ty())});
                    transfer->eraseFromParent();
                } else if (auto *set = dyn_cast<MemSetInst>(instruction)) {
                    Type *pointer = PointerType::get(module.getContext(), 0);
                    auto callee = module.getOrInsertFunction(
                        "memset",
                        FunctionType::get(
                            pointer, {pointer, builder.getInt32Ty(), builder.getInt32Ty()}, false));
                    builder.CreateCall(
                        callee,
                        {set->getRawDest(),
                         builder.CreateZExt(set->getValue(), builder.getInt32Ty()),
                         builder.CreateZExtOrTrunc(set->getLength(), builder.getInt32Ty())});
                    set->eraseFromParent();
                } else if (auto *call = dyn_cast<CallInst>(instruction)) {
                    auto host = hostFunctions.find(call->getCalledFunction());
                    if (host != hostFunctions.end()) {
                        SmallVector<Value *, 16> arguments;
                        unsigned index = 0;
                        for (Value *argument : call->args()) {
                            arguments.push_back(argument->getType()->isPointerTy() &&
                                                        !isHandle(host->second->getName(), index)
                                                    ? rebase(argument, true)
                                                    : argument);
                            ++index;
                        }
                        CallInst *replacement = builder.CreateCall(host->second, arguments);
                        replacement->setCallingConv(call->getCallingConv());
                        call->replaceAllUsesWith(replacement);
                        call->eraseFromParent();
                    } else if (call->isIndirectCall() && !call->isInlineAsm()) {
                        if (ios) {
                            // Written once by the host: native signed image base
                            // minus ELF image base. Code pages are never writable.
                            Value *slot = builder.CreateIntToPtr(builder.getInt64(bias + 0xff0000),
                                PointerType::get(module.getContext(), 272));
                            Value *delta = builder.CreateLoad(builder.getInt64Ty(), slot);
                            Value *offset = builder.CreatePtrToInt(call->getCalledOperand(), builder.getInt32Ty());
                            Value *address = builder.CreateAdd(delta, builder.CreateZExt(offset, builder.getInt64Ty()));
                            call->setCalledOperand(builder.CreateIntToPtr(address,
                                PointerType::get(module.getContext(), 272)));
                        } else {
                            call->setCalledOperand(rebase(call->getCalledOperand()));
                        }
                    }
                }
            }
        }
        // Late instruction selection must not turn memcmp/string calls back into
        // unrebased loads after this pass has handled the IR memory operations.
        for (Function &function : module)
            for (BasicBlock &block : function)
                for (Instruction &instruction : block)
                    if (auto *call = dyn_cast<CallInst>(&instruction))
                        if (!isa<IntrinsicInst>(call))
                            call->addFnAttr(Attribute::NoBuiltin);
        for (Function *old : declarations) {
            if (!old->use_empty())
                report_fatal_error("Unsupported address-taking use of a Halo host import");
            old->eraseFromParent();
        }
        return PreservedAnalyses::none();
    }
};
} // namespace
extern "C" LLVM_ATTRIBUTE_WEAK PassPluginLibraryInfo llvmGetPassPluginInfo() {
    return {LLVM_PLUGIN_API_VERSION, "HaloRebase", LLVM_VERSION_STRING, [](PassBuilder &builder) {
                builder.registerPipelineParsingCallback([](StringRef name,
                                                           ModulePassManager &manager,
                                                           ArrayRef<PassBuilder::PipelineElement>) {
                    if (name != "halo-rebase" && name != "halo-rebase-ios" && name != "halo-rebase-ios-mac-check")
                        return false;
                    // macOS reserves the iOS data arena on some OS versions.
                    // Source-only CI uses identical signed-image lowering with
                    // the Mac arena; the device pipeline retains its own bias.
                    manager.addPass(RebasePass(name != "halo-rebase", name == "halo-rebase-ios-mac-check"));
                    return true;
                });
            }};
}
