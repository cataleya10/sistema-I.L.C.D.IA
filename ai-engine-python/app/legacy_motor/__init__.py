from importlib import import_module
from typing import TYPE_CHECKING, Any

__all__ = [
    "ine_logic",
    "acta_logic",
    "curp_logic",
    "nss_logic",
    "csf_logic",
    "banco_logic",
    "domicilio_logic",
    "sepomex_loader",
]

if TYPE_CHECKING:
    from . import acta_logic as acta_logic
    from . import banco_logic as banco_logic
    from . import csf_logic as csf_logic
    from . import curp_logic as curp_logic
    from . import domicilio_logic as domicilio_logic
    from . import ine_logic as ine_logic
    from . import nss_logic as nss_logic
    from . import sepomex_loader as sepomex_loader


def __getattr__(name: str) -> Any:
    if name in __all__:
        module = import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
