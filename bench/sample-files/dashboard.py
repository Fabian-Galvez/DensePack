#!/usr/bin/env python
"""Start the live dashboard, from the repository or from an installed plugin.

    python "${CLAUDE_PLUGIN_ROOT}/scripts/dashboard.py" [--port 8788]

WHAT THIS FILE IS FOR, in plain words: the dashboard is not one file, it is
five. A marketplace install copies only what sits under plugin/, and today
four of the five sit in tools/ and bench/ instead, so an install has the
command and not the program. This file is the one door to the dashboard
wherever those five files are. It looks for each one beside itself first,
which is where an install carries them, then in tools/ and bench/ above it,
which is where the repository keeps them. It starts the same server either
way, and when a part is on neither path it says which part and where it
looked rather than raising ImportError at the user.

Every argument is passed straight through to tools/live_dashboard.py, so
--port, --session and --interval mean there what they mean here.

WHAT IS STILL OPEN, and is a decision rather than a default: whether the
four parts below move under plugin/scripts, which gives them one home and
makes an install complete but changes the file tools/DensePack Dashboard.vbs
starts, or whether they are copied there, which leaves that launcher alone
and adds four files that can drift apart from their originals. This file
works under either answer and needs no edit for either.
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent

# The five files the dashboard is: the page and its server, the plan meter
# it probes the rate limit header with, the token counter both of those
# call, and the two modules that hold the pricing arithmetic.
PARTS = ("live_dashboard.py", "plan_meter.py", "verify_tokens.py",
         "session_cost.py", "lead_receipt_cost.py")

# Where to look, in order. HERE is an installed plugin's scripts folder and
# holds every part once the packaging question above is settled. The other
# two are the repository checkout as it stands today.
SEARCH = (HERE, ROOT / "tools", ROOT / "bench")


def locate(parts=PARTS, search=SEARCH):
    """The folder each part was found in, and the parts found nowhere."""
    found, missing = {}, []
    for part in parts:
        for folder in search:
            if (folder / part).is_file():
                found[part] = folder
                break
        else:
            missing.append(part)
    return found, missing


def main():
    found, missing = locate()
    if missing:
        print("The dashboard cannot start. Not found: %s. Looked in: %s."
              % (", ".join(missing), ", ".join(str(f) for f in SEARCH)))
        return 1
    # dict.fromkeys keeps the first-seen order and drops the repeats, so
    # each folder is put on the path once and in search order.
    for folder in dict.fromkeys(found.values()):
        path = str(folder)
        if path not in sys.path:
            sys.path.insert(0, path)
    import live_dashboard
    return live_dashboard.main()


if __name__ == "__main__":
    sys.exit(main())
