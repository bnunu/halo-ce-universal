#include <errno.h>
int host_linux_errno(int value) {
#ifdef EPERM
    if (value == EPERM)
        return 1;
#endif
#ifdef ENOENT
    if (value == ENOENT)
        return 2;
#endif
#ifdef ESRCH
    if (value == ESRCH)
        return 3;
#endif
#ifdef EINTR
    if (value == EINTR)
        return 4;
#endif
#ifdef EIO
    if (value == EIO)
        return 5;
#endif
#ifdef ENXIO
    if (value == ENXIO)
        return 6;
#endif
#ifdef E2BIG
    if (value == E2BIG)
        return 7;
#endif
#ifdef ENOEXEC
    if (value == ENOEXEC)
        return 8;
#endif
#ifdef EBADF
    if (value == EBADF)
        return 9;
#endif
#ifdef ECHILD
    if (value == ECHILD)
        return 10;
#endif
#ifdef EAGAIN
    if (value == EAGAIN)
        return 11;
#endif
#ifdef ENOMEM
    if (value == ENOMEM)
        return 12;
#endif
#ifdef EACCES
    if (value == EACCES)
        return 13;
#endif
#ifdef EFAULT
    if (value == EFAULT)
        return 14;
#endif
#ifdef ENOTBLK
    if (value == ENOTBLK)
        return 15;
#endif
#ifdef EBUSY
    if (value == EBUSY)
        return 16;
#endif
#ifdef EEXIST
    if (value == EEXIST)
        return 17;
#endif
#ifdef EXDEV
    if (value == EXDEV)
        return 18;
#endif
#ifdef ENODEV
    if (value == ENODEV)
        return 19;
#endif
#ifdef ENOTDIR
    if (value == ENOTDIR)
        return 20;
#endif
#ifdef EISDIR
    if (value == EISDIR)
        return 21;
#endif
#ifdef EINVAL
    if (value == EINVAL)
        return 22;
#endif
#ifdef ENFILE
    if (value == ENFILE)
        return 23;
#endif
#ifdef EMFILE
    if (value == EMFILE)
        return 24;
#endif
#ifdef ENOTTY
    if (value == ENOTTY)
        return 25;
#endif
#ifdef ETXTBSY
    if (value == ETXTBSY)
        return 26;
#endif
#ifdef EFBIG
    if (value == EFBIG)
        return 27;
#endif
#ifdef ENOSPC
    if (value == ENOSPC)
        return 28;
#endif
#ifdef ESPIPE
    if (value == ESPIPE)
        return 29;
#endif
#ifdef EROFS
    if (value == EROFS)
        return 30;
#endif
#ifdef EMLINK
    if (value == EMLINK)
        return 31;
#endif
#ifdef EPIPE
    if (value == EPIPE)
        return 32;
#endif
#ifdef EDOM
    if (value == EDOM)
        return 33;
#endif
#ifdef ERANGE
    if (value == ERANGE)
        return 34;
#endif
#ifdef EDEADLK
    if (value == EDEADLK)
        return 35;
#endif
#ifdef ENAMETOOLONG
    if (value == ENAMETOOLONG)
        return 36;
#endif
#ifdef ENOLCK
    if (value == ENOLCK)
        return 37;
#endif
#ifdef ENOSYS
    if (value == ENOSYS)
        return 38;
#endif
#ifdef ENOTEMPTY
    if (value == ENOTEMPTY)
        return 39;
#endif
#ifdef ELOOP
    if (value == ELOOP)
        return 40;
#endif
#ifdef ENOMSG
    if (value == ENOMSG)
        return 42;
#endif
#ifdef EIDRM
    if (value == EIDRM)
        return 43;
#endif
#ifdef ECHRNG
    if (value == ECHRNG)
        return 44;
#endif
#ifdef EL2NSYNC
    if (value == EL2NSYNC)
        return 45;
#endif
#ifdef EL3HLT
    if (value == EL3HLT)
        return 46;
#endif
#ifdef EL3RST
    if (value == EL3RST)
        return 47;
#endif
#ifdef ELNRNG
    if (value == ELNRNG)
        return 48;
#endif
#ifdef EUNATCH
    if (value == EUNATCH)
        return 49;
#endif
#ifdef ENOCSI
    if (value == ENOCSI)
        return 50;
#endif
#ifdef EL2HLT
    if (value == EL2HLT)
        return 51;
#endif
#ifdef EBADE
    if (value == EBADE)
        return 52;
#endif
#ifdef EBADR
    if (value == EBADR)
        return 53;
#endif
#ifdef EXFULL
    if (value == EXFULL)
        return 54;
#endif
#ifdef ENOANO
    if (value == ENOANO)
        return 55;
#endif
#ifdef EBADRQC
    if (value == EBADRQC)
        return 56;
#endif
#ifdef EBADSLT
    if (value == EBADSLT)
        return 57;
#endif
#ifdef EBFONT
    if (value == EBFONT)
        return 59;
#endif
#ifdef ENOSTR
    if (value == ENOSTR)
        return 60;
#endif
#ifdef ENODATA
    if (value == ENODATA)
        return 61;
#endif
#ifdef ETIME
    if (value == ETIME)
        return 62;
#endif
#ifdef ENOSR
    if (value == ENOSR)
        return 63;
#endif
#ifdef ENONET
    if (value == ENONET)
        return 64;
#endif
#ifdef ENOPKG
    if (value == ENOPKG)
        return 65;
#endif
#ifdef EREMOTE
    if (value == EREMOTE)
        return 66;
#endif
#ifdef ENOLINK
    if (value == ENOLINK)
        return 67;
#endif
#ifdef EADV
    if (value == EADV)
        return 68;
#endif
#ifdef ESRMNT
    if (value == ESRMNT)
        return 69;
#endif
#ifdef ECOMM
    if (value == ECOMM)
        return 70;
#endif
#ifdef EPROTO
    if (value == EPROTO)
        return 71;
#endif
#ifdef EMULTIHOP
    if (value == EMULTIHOP)
        return 72;
#endif
#ifdef EDOTDOT
    if (value == EDOTDOT)
        return 73;
#endif
#ifdef EBADMSG
    if (value == EBADMSG)
        return 74;
#endif
#ifdef EOVERFLOW
    if (value == EOVERFLOW)
        return 75;
#endif
#ifdef ENOTUNIQ
    if (value == ENOTUNIQ)
        return 76;
#endif
#ifdef EBADFD
    if (value == EBADFD)
        return 77;
#endif
#ifdef EREMCHG
    if (value == EREMCHG)
        return 78;
#endif
#ifdef ELIBACC
    if (value == ELIBACC)
        return 79;
#endif
#ifdef ELIBBAD
    if (value == ELIBBAD)
        return 80;
#endif
#ifdef ELIBSCN
    if (value == ELIBSCN)
        return 81;
#endif
#ifdef ELIBMAX
    if (value == ELIBMAX)
        return 82;
#endif
#ifdef ELIBEXEC
    if (value == ELIBEXEC)
        return 83;
#endif
#ifdef EILSEQ
    if (value == EILSEQ)
        return 84;
#endif
#ifdef ERESTART
    if (value == ERESTART)
        return 85;
#endif
#ifdef ESTRPIPE
    if (value == ESTRPIPE)
        return 86;
#endif
#ifdef EUSERS
    if (value == EUSERS)
        return 87;
#endif
#ifdef ENOTSOCK
    if (value == ENOTSOCK)
        return 88;
#endif
#ifdef EDESTADDRREQ
    if (value == EDESTADDRREQ)
        return 89;
#endif
#ifdef EMSGSIZE
    if (value == EMSGSIZE)
        return 90;
#endif
#ifdef EPROTOTYPE
    if (value == EPROTOTYPE)
        return 91;
#endif
#ifdef ENOPROTOOPT
    if (value == ENOPROTOOPT)
        return 92;
#endif
#ifdef EPROTONOSUPPORT
    if (value == EPROTONOSUPPORT)
        return 93;
#endif
#ifdef ESOCKTNOSUPPORT
    if (value == ESOCKTNOSUPPORT)
        return 94;
#endif
#ifdef EOPNOTSUPP
    if (value == EOPNOTSUPP)
        return 95;
#endif
#ifdef EPFNOSUPPORT
    if (value == EPFNOSUPPORT)
        return 96;
#endif
#ifdef EAFNOSUPPORT
    if (value == EAFNOSUPPORT)
        return 97;
#endif
#ifdef EADDRINUSE
    if (value == EADDRINUSE)
        return 98;
#endif
#ifdef EADDRNOTAVAIL
    if (value == EADDRNOTAVAIL)
        return 99;
#endif
#ifdef ENETDOWN
    if (value == ENETDOWN)
        return 100;
#endif
#ifdef ENETUNREACH
    if (value == ENETUNREACH)
        return 101;
#endif
#ifdef ENETRESET
    if (value == ENETRESET)
        return 102;
#endif
#ifdef ECONNABORTED
    if (value == ECONNABORTED)
        return 103;
#endif
#ifdef ECONNRESET
    if (value == ECONNRESET)
        return 104;
#endif
#ifdef ENOBUFS
    if (value == ENOBUFS)
        return 105;
#endif
#ifdef EISCONN
    if (value == EISCONN)
        return 106;
#endif
#ifdef ENOTCONN
    if (value == ENOTCONN)
        return 107;
#endif
#ifdef ESHUTDOWN
    if (value == ESHUTDOWN)
        return 108;
#endif
#ifdef ETOOMANYREFS
    if (value == ETOOMANYREFS)
        return 109;
#endif
#ifdef ETIMEDOUT
    if (value == ETIMEDOUT)
        return 110;
#endif
#ifdef ECONNREFUSED
    if (value == ECONNREFUSED)
        return 111;
#endif
#ifdef EHOSTDOWN
    if (value == EHOSTDOWN)
        return 112;
#endif
#ifdef EHOSTUNREACH
    if (value == EHOSTUNREACH)
        return 113;
#endif
#ifdef EALREADY
    if (value == EALREADY)
        return 114;
#endif
#ifdef EINPROGRESS
    if (value == EINPROGRESS)
        return 115;
#endif
#ifdef ESTALE
    if (value == ESTALE)
        return 116;
#endif
#ifdef EUCLEAN
    if (value == EUCLEAN)
        return 117;
#endif
#ifdef ENOTNAM
    if (value == ENOTNAM)
        return 118;
#endif
#ifdef ENAVAIL
    if (value == ENAVAIL)
        return 119;
#endif
#ifdef EISNAM
    if (value == EISNAM)
        return 120;
#endif
#ifdef EREMOTEIO
    if (value == EREMOTEIO)
        return 121;
#endif
#ifdef EDQUOT
    if (value == EDQUOT)
        return 122;
#endif
#ifdef ENOMEDIUM
    if (value == ENOMEDIUM)
        return 123;
#endif
#ifdef EMEDIUMTYPE
    if (value == EMEDIUMTYPE)
        return 124;
#endif
#ifdef ECANCELED
    if (value == ECANCELED)
        return 125;
#endif
#ifdef ENOKEY
    if (value == ENOKEY)
        return 126;
#endif
#ifdef EKEYEXPIRED
    if (value == EKEYEXPIRED)
        return 127;
#endif
#ifdef EKEYREVOKED
    if (value == EKEYREVOKED)
        return 128;
#endif
#ifdef EKEYREJECTED
    if (value == EKEYREJECTED)
        return 129;
#endif
#ifdef EOWNERDEAD
    if (value == EOWNERDEAD)
        return 130;
#endif
#ifdef ENOTRECOVERABLE
    if (value == ENOTRECOVERABLE)
        return 131;
#endif
#ifdef ERFKILL
    if (value == ERFKILL)
        return 132;
#endif
#ifdef EHWPOISON
    if (value == EHWPOISON)
        return 133;
#endif
    return value ? 5 : 0;
}
