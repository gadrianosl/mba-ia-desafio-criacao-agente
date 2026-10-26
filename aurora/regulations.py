"""Busca local por assunto e artigo, sem inserir o documento inteiro no ADK."""
import re
import unicodedata

from aurora.config import PROJECT_ROOT

STOPWORDS = set('a o as os de da do das dos em no na nos nas um uma e ou que qual quais como para por com se ao aos ate quando sobre quero saber funciona funcionamento horario horas sao tem pode posso'.split())
ALIASES = {'cachorro': 'animais', 'gato': 'animais', 'pet': 'animais',
           'barulho': 'silencio', 'reforma': 'reformas', 'obra': 'obras',
           'lixeira': 'lixo', 'estacionamento': 'garagem'}


def tokens(text):
    plain = ''.join(c for c in unicodedata.normalize('NFD', text.lower())
                    if unicodedata.category(c) != 'Mn')
    words = re.findall(r'[a-z0-9]+', plain)
    return {ALIASES.get(w, w) for w in words if len(w) > 2 and w not in STOPWORDS}


def search_regulations(question):
    """Retorna até dois artigos de um único capítulo pertinente à consulta.

    Sem evidência lexical, pede esclarecimento em vez de retornar capítulos
    arbitrários. O arquivo completo existe apenas na memória deste buscador.
    """
    query = tokens(question)
    document = (PROJECT_ROOT / 'dados' / 'regulamento.md').read_text()
    chapters = []
    for section in re.split(r'^## ', document, flags=re.MULTILINE)[1:]:
        title, _, body = section.partition('\n')
        articles = [a.strip() for a in re.split(r'(?=^\*\*Art\. \d+\.)', body, flags=re.MULTILINE) if a.strip()]
        title_words = tokens(title) - {'capitulo'}
        title_score = len(query & title_words)
        article_scores = [(len(query & tokens(a)), a) for a in articles]
        best = max((score for score, _ in article_scores), default=0)
        chapters.append((title_score, best, title, article_scores))
    if not query or not chapters:
        return {'status': 'esclarecer', 'trechos': []}
    title_score, best, title, articles = max(chapters, key=lambda c: (c[0], c[1]))
    if not title_score and not best:
        return {'status': 'esclarecer', 'trechos': []}
    selected = sorted(articles, key=lambda item: item[0], reverse=True)
    selected = [article for score, article in selected[:2] if score > 0]
    return {'status': 'encontrado', 'fonte': 'dados/regulamento.md',
            'capitulo': title, 'trechos': selected}
