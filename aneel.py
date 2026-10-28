#!/usr/bin/env python3
"""
Acesso aos dados abertos da ANEEL com tolerância a queda do portal.

- com_tentativas(fn, oque): roda fn() e, em erro de rede (tempo esgotado, conexão recusada/caída, HTTP 5xx ou 429),
  tenta de novo depois de 1, 3 e 6 minutos. Se a ANEEL continuar fora, levanta AneelFora. Depois que uma etapa concluiu
  que a ANEEL está fora, as próximas etapas da mesma rodada fazem uma tentativa só (não ficam esperando de novo).
- executar(main, etapa): roda main(); se a ANEEL estiver fora, encerra com AVISO (código 0, mantém os dados publicados)
  e conta o dia em aneel_falhas.json. A partir de DIAS_ERRO dias seguidos fora, encerra com ERRO (o GitHub manda o
  e-mail). Uma rodada que funciona zera a contagem da etapa.
"""
import datetime, http.client, json, os, socket, sys, tempfile, time, urllib.error

AQUI = os.path.dirname(os.path.abspath(__file__))
FALHAS = os.path.join(AQUI, 'aneel_falhas.json')
SINAL_FORA = os.path.join(tempfile.gettempdir(), 'aneel_fora')   # vale só para a rodada atual (máquina do GitHub)
ESPERAS = [60, 180, 360]                                         # segundos entre as tentativas
DIAS_ERRO = 3


class AneelFora(Exception):
    pass


def _log(*a):
    print(datetime.datetime.now().strftime('%H:%M:%S'), *a, flush=True)


def transitorio(e):
    """Erro de rede ou do servidor da ANEEL (vale tentar de novo), e não erro do nosso código ou do arquivo."""
    if isinstance(e, urllib.error.HTTPError):
        return e.code >= 500 or e.code == 429
    return isinstance(e, (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError,
                          http.client.RemoteDisconnected, http.client.IncompleteRead))


def com_tentativas(fn, oque):
    esperas = [] if os.path.exists(SINAL_FORA) else ESPERAS
    for n in range(len(esperas) + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 — só os erros de rede são tratados aqui; o resto sobe
            if not transitorio(e):
                raise
            if n == len(esperas):
                open(SINAL_FORA, 'w').write(datetime.datetime.now().isoformat())
                raise AneelFora(f'{oque}: {e}') from e
            _log(f'ANEEL não respondeu ({oque}: {e}); nova tentativa em {esperas[n] // 60} min')
            time.sleep(esperas[n])


def _ler():
    try:
        return json.load(open(FALHAS, encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _gravar(d):
    d = {k: v for k, v in d.items() if v}
    if d:
        json.dump(d, open(FALHAS, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        open(FALHAS, 'a').write('\n')
    elif os.path.exists(FALHAS):
        os.remove(FALHAS)


def _saida(chave, valor):
    if os.environ.get('GITHUB_OUTPUT'):
        open(os.environ['GITHUB_OUTPUT'], 'a').write(f'{chave}={valor}\n')


def executar(main, etapa):
    try:
        main()
    except AneelFora as e:
        hoje = datetime.date.today().isoformat()
        d = _ler()
        dias = sorted(set(d.get(etapa, [])) | {hoje})
        d[etapa] = dias
        _gravar(d)
        _saida('novo', 'false')
        msg = (f'Portal de dados abertos da ANEEL fora do ar ({e}). Nada foi publicado: o cadastro continua com os dados '
               f'anteriores. Dias seguidos sem conseguir: {len(dias)} ({", ".join(dias)}).')
        if len(dias) >= DIAS_ERRO:
            print(f'::error title=ANEEL fora há {len(dias)} dias ({etapa})::{msg}', flush=True)
            return 1
        print(f'::warning title=ANEEL fora do ar ({etapa})::{msg} Tenta de novo na próxima rodada; '
              f'vira erro a partir de {DIAS_ERRO} dias seguidos.', flush=True)
        return 0
    d = _ler()
    if d.pop(etapa, None):
        _log('ANEEL voltou: contagem de dias fora zerada para', etapa)
        _gravar(d)
    return 0


if __name__ == '__main__':
    sys.exit('módulo auxiliar: use tarifas.py ou mercado_gd.py')
