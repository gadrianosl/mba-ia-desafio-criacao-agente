"""Restauração explícita: uv run python -m aurora.reset."""
import argparse
from pathlib import Path

from aurora.storage import DEFAULT_DATABASE, Storage


def main():
    parser = argparse.ArgumentParser(description='Restaura os dados iniciais e apaga vínculos e pendências de sessões. Pare a API antes de executar.')
    parser.add_argument('--database', type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args()
    Storage(args.database).reset()
    print('Dados iniciais restaurados; vínculos e pendências removidos.')


if __name__ == '__main__':
    main()
