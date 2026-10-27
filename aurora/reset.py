"""Restauração explícita: uv run python -m aurora.reset (pare a API antes)."""
import argparse
from pathlib import Path

from aurora.config import PROJECT_ROOT
from aurora.storage import Storage


def reset_runtime(directory):
    """Restaura negócio e remove histórico ADK. Exige aplicação parada."""
    directory = Path(directory)
    Storage(directory / 'business.sqlite3').reset()
    for suffix in ('', '-wal', '-shm', '-journal'):
        (directory / ('sessions.sqlite3' + suffix)).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description='Restaura os dados iniciais e apaga sessões, eventos e pendências. Pare a API e o chat antes de executar.')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--directory', type=Path,
                       help='Diretório do runtime; padrão: .local/runtime do projeto')
    group.add_argument('--database', type=Path,
                       help='Modo legado: restaura apenas o banco de negócio indicado, sem apagar eventos ADK')
    args = parser.parse_args()
    if args.database is not None:
        Storage(args.database).reset()
        print('Banco de negócio restaurado; histórico ADK não alterado.')
    else:
        reset_runtime(args.directory or PROJECT_ROOT / '.local' / 'runtime')
        print('Dados iniciais restaurados; sessões, eventos e pendências removidos.')


if __name__ == '__main__':
    main()
