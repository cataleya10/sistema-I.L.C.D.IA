import argparse
import asyncio
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.document_audit import audit_folder


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audita una carpeta completa de documentos usando el pipeline real."
    )
    parser.add_argument("folder", help="Ruta completa de la carpeta a auditar.")
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximo de archivos a procesar.",
    )
    parser.add_argument(
        "--no-recurse",
        action="store_true",
        help="No recorrer subcarpetas.",
    )
    parser.add_argument(
        "--issues-only",
        action="store_true",
        help="Mostrar solo documentos con issues o errores.",
    )
    return parser


async def _async_main(args: argparse.Namespace) -> int:
    result = await audit_folder(
        args.folder,
        recurse=not args.no_recurse,
        limit=args.limit,
        issues_only=args.issues_only,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
