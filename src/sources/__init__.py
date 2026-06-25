from .sina import SinaAdapter
from .wallstreetcn import WallStreetCNAdapter
from .cls import CLSAdapter
from .bloomberg import BloombergAdapter
from .reuters import ReutersAdapter

__all__ = [
    "SinaAdapter",
    "WallStreetCNAdapter",
    "CLSAdapter",
    "BloombergAdapter",
    "ReutersAdapter",
]

ADAPTER_MAP = {
    "sina": SinaAdapter,
    "wallstreetcn": WallStreetCNAdapter,
    "cls": CLSAdapter,
    "bloomberg": BloombergAdapter,
    "reuters": ReutersAdapter,
}


def get_adapter(name: str):
    cls = ADAPTER_MAP.get(name)
    if cls is None:
        raise ValueError(f"Unknown source adapter: {name}")
    return cls()
