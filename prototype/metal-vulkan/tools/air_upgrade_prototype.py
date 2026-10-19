"""Prototype: rewrite Metal 2.2-era AIR (text IR) into the call forms metal2vulkan 0.2 decodes.

air_upgrade.py <in.ll> <out.ll>
"""
import re
import sys

ACCESS = {"air.sample": 0, "air.read": 1, "air.write": 2, "air.read_write": 3}


def split_args(text):
    """Top-level comma split of a call or declaration argument list."""
    out, depth, start = [], 0, 0
    for i, c in enumerate(text):
        if c in "<({[":
            depth += 1
        elif c in ">)}]":
            depth -= 1
        elif c == "," and depth == 0:
            out.append(text[start:i].strip())
            start = i + 1
    tail = text[start:].strip()
    if tail:
        out.append(tail)
    return out


def matching_paren(text, open_at):
    depth = 0
    for i in range(open_at, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    raise ValueError("unbalanced")


def family(name):
    """The rewrite an air.* intrinsic needs, or None."""
    if re.match(r"air\.sample_texture_\w+?_grad\.", name):
        return "sample_grad"
    if name.startswith("air.sample_texture_") or name.startswith("air.sample_depth_"):
        return "sample"
    if name.startswith("air.gather_texture_") or name.startswith("air.gather_depth_"):
        return "gather"
    if name.startswith("air.read_texture_") or name.startswith("air.read_depth_"):
        return "read"
    if name.startswith("air.write_texture_"):
        return "write"
    if name.startswith("air.atomic.global.") or name.startswith("air.atomic.local."):
        return "atomic"
    return None


def upgrade(text):
    lines = text.split("\n")
    # The entry's parameters are %0 .. %n-1; texture arguments carry their access in metadata.
    access = {}
    for line in lines:
        m = re.match(r'!\d+ = !\{i32 (\d+), !"air\.texture".*?!"(air\.(?:sample|read|write|read_write))"', line)
        if m:
            access[int(m.group(1))] = ACCESS[m.group(2)]
    params = 0
    for line in lines:
        if line.startswith("define ") and "@main0(" in line:
            start = line.index("@main0(") + len("@main0")
            params = len(split_args(line[start + 1:matching_paren(line, start)]))
            break

    def access_of(arg, kind):
        m = re.search(r"%(\d+)$", arg)
        if m and int(m.group(1)) < params and int(m.group(1)) in access:
            return access[int(m.group(1))]
        return {"read": 1, "write": 2}.get(kind, 0)

    def rewrite_args(kind, args, texture, decl=False):
        args = list(args)
        zero = "float" if decl else "float 0.000000e+00"
        if kind in ("sample", "gather", "read", "write", "sample_grad"):
            acc = "i32" if decl else f"i32 {access_of(texture, kind)}"
            if kind == "sample":
                args.append(zero)
            if kind == "sample_grad":
                # min_lod_clamp goes after dpdy, before the offset flag (the last i1).
                flag = next(i for i in range(len(args) - 1, -1, -1) if args[i].split()[0] == "i1")
                args.insert(flag, zero)
            args.append(acc)
        elif kind == "atomic":
            args.append("i1" if decl else "i1 false")
        return args

    # A fragment output names its attachment and (since AIR 2.3) its dual-source index.
    lines = [re.sub(r'(!"air\.render_target", i32 \d+)(, !"|\})', r'\1, i32 0\2', line) for line in lines]
    status_kinds = ("sample", "sample_grad", "gather", "read")
    out = []
    counter = [0]
    for line in lines:
        m = re.match(r"declare (.+?) @(air\.[\w.]+)\((.*)\)(.*)$", line)
        if m and family(m.group(2)):
            kind = family(m.group(2))
            ret, args = m.group(1), split_args(m.group(3))
            # Declarations carry types only (with attributes): placeholders keep their positions.
            new_args = rewrite_args(kind, args, None, decl=True)
            if kind in status_kinds:
                ret = "{ " + ret + ", i8 }"
            out.append(f"declare {ret} @{m.group(2)}({', '.join(new_args)}){m.group(4)}")
            continue
        m = re.match(r"(\s*)(%[\w.]+) = (tail call|call|notail call) (.+?) @(air\.[\w.]+)\(", line)
        m_void = re.match(r"(\s*)(tail call|call|notail call) void @(air\.[\w.]+)\(", line)
        if m and family(m.group(5)):
            kind = family(m.group(5))
            open_at = line.index("@" + m.group(5) + "(") + len(m.group(5)) + 1
            close = matching_paren(line, open_at)
            args = split_args(line[open_at + 1:close])
            new_args = rewrite_args(kind, args, args[0] if args else None)
            ret = m.group(4)
            rest = line[close + 1:]
            if kind in status_kinds:
                counter[0] += 1
                temp = f"%qm.status.{counter[0]}"
                struct = "{ " + ret + ", i8 }"
                out.append(f"{m.group(1)}{temp} = {m.group(3)} {struct} @{m.group(5)}({', '.join(new_args)}){rest}")
                out.append(f"{m.group(1)}{m.group(2)} = extractvalue {struct} {temp}, 0")
            else:
                out.append(f"{m.group(1)}{m.group(2)} = {m.group(3)} {ret} @{m.group(5)}({', '.join(new_args)}){rest}")
            continue
        if m_void and family(m_void.group(3)):
            kind = family(m_void.group(3))
            open_at = line.index("@" + m_void.group(3) + "(") + len(m_void.group(3)) + 1
            close = matching_paren(line, open_at)
            args = split_args(line[open_at + 1:close])
            new_args = rewrite_args(kind, args, args[0] if args else None)
            out.append(f"{m_void.group(1)}{m_void.group(2)} void @{m_void.group(3)}({', '.join(new_args)}){line[close + 1:]}")
            continue
        out.append(line)
    return "\n".join(out)


if __name__ == "__main__":
    open(sys.argv[2], "w").write(upgrade(open(sys.argv[1]).read()))
