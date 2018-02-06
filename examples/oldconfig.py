# Implements oldconfig-like functionality:
#
#   1. Load existing .config
#   2. Prompt the user for the value of all changeable symbols/choices
#      that aren't already set in the .config
#   3. Write new .config
#
# Unlike 'make oldconfig', this script doesn't print menu titles and
# comments, but instead gives the Kconfig locations of all symbols and
# choices. Printing menu titles and comments as well would be pretty easy to
# add (look at the parents of each item and print all menu prompts and
# comments unless they have already been printed).
#
# Sample session:
#
#   OldconfigExample contents:
#
#     config MODULES
#             def_bool y
#             option modules
#
#     config BOOL_SYM
#             bool "BOOL_SYM prompt"
#             default y
#
#     config TRISTATE_SYM
#             tristate "TRISTATE_SYM prompt"
#             default m
#
#     config STRING_SYM
#             string "STRING_SYM prompt"
#             default "foo"
#
#     config INT_SYM
#             int "INT_SYM prompt"
#
#     config HEX_SYM
#             hex "HEX_SYM prompt"
#
#     choice
#             bool "A choice that defaults to CHOICE_B"
#             default CHOICE_B
#
#     config CHOICE_A
#             bool "CHOICE_A's prompt"
#
#     config CHOICE_B
#             bool "CHOICE_B's prompt"
#
#     config CHOICE_C
#             bool "CHOICE_C's prompt"
#
#     endchoice
#
#
#   Running:
#
#     $ touch .config  # Run with empty .config
#
#     $ python oldconfig.py Kconfig
#     BOOL_SYM prompt (BOOL_SYM, defined at Kconfig:5) [n/Y] foo
#     Invalid tristate value
#     BOOL_SYM prompt (BOOL_SYM, defined at Kconfig:5) [n/Y] n
#     TRISTATE_SYM prompt (TRISTATE_SYM, defined at Kconfig:9) [n/M/y]
#     STRING_SYM prompt (STRING_SYM, defined at Kconfig:13) [foo] bar
#     INT_SYM prompt (INT_SYM, defined at Kconfig:17) [] 0x123
#     warning: the value '0x123' is invalid for INT_SYM (defined at Kconfig:17), which has type int. Assignment ignored.
#     INT_SYM prompt (INT_SYM, defined at Kconfig:17) [] 123
#     HEX_SYM prompt (HEX_SYM, defined at Kconfig:20) [] 0x123
#     A choice that default to B (defined at Kconfig:23)
#       1. CHOICE_A's prompt (CHOICE_A)
#     > 2. CHOICE_B's prompt (CHOICE_B)
#       3. CHOICE_C's prompt (CHOICE_C)
#     choice[1-3]: 5
#     Bad index
#     A choice that default to B (defined at Kconfig:23)
#       1. CHOICE_A's prompt (CHOICE_A)
#     > 2. CHOICE_B's prompt (CHOICE_B)
#       3. CHOICE_C's prompt (CHOICE_C)
#     choice[1-3]: 3
#     Configuration written to .config
#
#     $ cat .config
#     # Generated by Kconfiglib (https://github.com/ulfalizer/Kconfiglib)
#     CONFIG_MODULES=y
#     # CONFIG_BOOL_SYM is not set
#     CONFIG_TRISTATE_SYM=m
#     CONFIG_STRING_SYM="bar"
#     CONFIG_INT_SYM=123
#     CONFIG_HEX_SYM=0x123
#     # CONFIG_CHOICE_A is not set
#     # CONFIG_CHOICE_B is not set
#     CONFIG_CHOICE_C=y
#
#     $ python oldconfig.py Kconfig  # Everything's already up to date
#     Configuration written to .config
from __future__ import print_function
from kconfiglib import Kconfig, Symbol, Choice, BOOL, TRISTATE, HEX, STR_TO_TRI
import os
import sys

# Python 2/3 compatibility hack
if sys.version_info[0] < 3:
    input = raw_input

def eprint(*args):
    print(*args, file=sys.stderr)

def name_and_loc_str(sym):
    """
    Helper for printing the symbol name along with the location(s) in the
    Kconfig files where it is defined
    """
    return "{}, defined at {}".format(
        sym.name,
        ", ".join("{}:{}".format(node.filename, node.linenr)
                  for node in sym.nodes))

def default_value_str(sym):
    """
    Returns the "m/M/y" string in e.g.

      TRISTATE_SYM prompt (TRISTATE_SYM, defined at Kconfig:9) [n/M/y]:

    For string/int/hex, returns the default value as-is.
    """
    if sym.type in (BOOL, TRISTATE):
        res = []

        if 0 in sym.assignable:
            res.append("N" if sym.tri_value == 0 else "n")

        if 1 in sym.assignable:
            res.append("M" if sym.tri_value == 1 else "m")

        if 2 in sym.assignable:
            res.append("Y" if sym.tri_value == 2 else "y")

        return "/".join(res)

    # string/int/hex
    return sym.str_value

def do_oldconfig_for_node(node):
    """
    Prompts the user for a value for the menu node item, where applicable in
    oldconfig mode
    """
    # Only symbols and choices can be configured
    if not isinstance(node.item, (Symbol, Choice)):
        return

    # Skip symbols and choices that aren't visible
    if not node.item.visibility:
        return

    # Skip symbols and choices that don't have a prompt (at this location)
    if not node.prompt:
        return

    if isinstance(node.item, Symbol):
        sym = node.item

        # Skip symbols that already have a user value
        if sym.user_value is not None:
            return

        # Skip symbols that can only have a single value, due to selects
        if len(sym.assignable) == 1:
            return

        # Skip symbols in choices in y mode. We ask once for the entire choice
        # instead.
        if sym.choice and sym.choice.tri_value == 2:
            return

        # Loop until the user enters a valid value or enters a blank string
        # (for the default value)
        while True:
            val = input("{} ({}) [{}] ".format(
                            node.prompt[0], name_and_loc_str(sym),
                            default_value_str(sym)))

            # Substitute a blank string with the default value the symbol
            # would get
            if not val:
                val = sym.str_value

            if sym.type in (BOOL, TRISTATE):
                if val not in STR_TO_TRI:
                    eprint("Invalid tristate value")
                    continue
                val = STR_TO_TRI[val]

            # Automatically add a "0x" prefix for hex symbols, like the
            # menuconfig interface does. This isn't done when loading .config
            # files, hence why set_value() doesn't do it automatically.
            if sym.type == HEX and not val.startswith(("0x", "0X")):
                val = "0x" + val

            # Kconfiglib itself will print a warning here if the value
            # is invalid, so we don't need to bother
            if sym.set_value(val):
                # Valid value input. We're done with this node.
                return

    else:
        choice = node.item

        # Skip choices that already have a visible user selection
        if choice.user_selection and choice.user_selection.visibility == 2:
            return

        # Get a list of available selections. The mode of the choice limits
        # the visibility of the choice value symbols, so this will indirectly
        # skip choices in n and m mode.
        options = [sym for sym in choice.syms if sym.visibility == 2]

        # No y-visible choice value symbols
        if not options:
            return

        # Loop until the user enters a valid selection or a blank string (for
        # the default selection)
        while True:
            print("{} (defined at {}:{})".format(
                node.prompt[0], node.filename, node.linenr))

            for i, sym in enumerate(options, 1):
                print("{} {}. {} ({})".format(
                    ">" if choice.selection is sym else " ",
                    i,
                    # Assume people don't define choice symbols with multiple
                    # prompts. That generates a warning anyway.
                    sym.nodes[0].prompt[0],
                    sym.name))

            sel_index = input("choice[1-{}]: ".format(len(options)))

            # Pick the default selection if the string is blank
            if not sel_index:
                choice.selection.set_value(2)
                return

            try:
                sel_index = int(sel_index)
            except ValueError:
                eprint("Bad index")
                continue

            if not 1 <= sel_index <= len(options):
                eprint("Bad index")
                continue

            # Valid selection
            options[sel_index - 1].set_value(2)
            return

def do_oldconfig(node):
    while node:
        do_oldconfig_for_node(node)

        if node.list:
            do_oldconfig(node.list)

        node = node.next

if __name__ == "__main__":
    if len(sys.argv) != 2:
        eprint("error: pass name of base Kconfig file as argument")
        sys.exit(1)

    if not os.path.exists(".config"):
        eprint("error: no existing .config")
        sys.exit(1)

    kconf = Kconfig(sys.argv[1])

    kconf.load_config(".config")
    do_oldconfig(kconf.top_node)
    kconf.write_config(".config")

    print("Configuration written to .config")
