"""Turn the small editable helmet SVG into a native resolution-independent PDF.

Only absolute M/L/C/Z commands are accepted; no web renderer or build dependency.
"""
from pathlib import Path
import re
import xml.etree.ElementTree as ET


def render(source: Path, destination: Path):
    svg = ET.parse(source).getroot()
    commands = ["0 0 0 rg", "1 0 0 -1 0 24 cm"]
    for path in svg.findall("{http://www.w3.org/2000/svg}path"):
        tokens = re.findall(r"[A-Za-z]|-?\d+(?:\.\d+)?", path.attrib["d"])
        index = 0
        while index < len(tokens):
            operation = tokens[index]
            count, pdf = {"M": (2, "m"), "L": (2, "l"), "C": (6, "c"), "Z": (0, "h")}[operation]
            commands.append(" ".join(tokens[index + 1:index + count + 1] + [pdf]))
            index += count + 1
        commands.append("f*" if path.get("fill-rule") == "evenodd" else "f")
    stream = "\n".join(commands).encode("ascii")
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 24 24] /Resources << >> /Contents 4 0 R >>",
               b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"]
    document = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(document))
        document.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(document)
    document.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        document.extend(f"{offset:010d} 00000 n \n".encode())
    document.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    destination.write_bytes(document)
