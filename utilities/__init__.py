# Compatibility shim: some cogs import `from utilities.database import db`.
# The real modules live under cogs.utilities; this package re-exports them.