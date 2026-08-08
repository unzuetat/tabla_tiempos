#!/usr/bin/env python3
"""Fusiona varias bibliotecas de la tabla de tiempos en una sola.

Cada navegador que abre la tabla de tiempos genera su propio código de
biblioteca. Si se han usado códigos distintos para sets distintos, los sets
quedan repartidos y no se sincronizan entre sí. Esto los junta en una única
biblioteca, con **una hoja por set**, que es como está pensado.

    # Ver qué haría, sin tocar nada (por defecto):
    python3 fusionar-bibliotecas.py codigo1 codigo2 codigo3

    # Hacerlo de verdad, dejando todo en la primera:
    python3 fusionar-bibliotecas.py codigo1 codigo2 codigo3 --aplicar

    # Elegir otro destino:
    python3 fusionar-bibliotecas.py cod1 cod2 --destino cod2 --aplicar

Antes de escribir nada guarda una copia de cada biblioteca en `backups/`.
Escribe con PATCH, no con PUT, para no borrar el catálogo ni el libro que
Masterizer publica en el mismo nodo.
"""
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

DB_URL = "https://tabla-tiempos-default-rtdb.europe-west1.firebasedatabase.app"
BACKUP_DIR = Path(__file__).parent / "backups"


def _ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _request(url, method="GET", body=None):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20, context=_ctx()) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else None


def node_url(code, child=""):
    path = "libraries/{}".format(urllib.parse.quote(code, safe=""))
    if child:
        path += "/" + child
    return "{}/{}.json".format(DB_URL, path)


def fetch_doc(code):
    """Devuelve (documento, nodo_crudo). El documento viaja como string JSON."""
    node = _request(node_url(code))
    if not node:
        return None, None
    data = node.get("data") if isinstance(node, dict) else None
    if not isinstance(data, str):
        return None, node
    try:
        return json.loads(data), node
    except ValueError:
        return None, node


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    apply_it = "--aplicar" in flags
    dest = None
    for f in flags:
        if f.startswith("--destino="):
            dest = f.split("=", 1)[1]
    if "--destino" in flags:
        i = sys.argv.index("--destino")
        if i + 1 < len(sys.argv):
            dest = sys.argv[i + 1]
            args = [a for a in args if a != dest] + [dest]

    codes = []
    for c in args:
        c = "".join(ch for ch in c.lower() if ch.isalnum())
        if c and c not in codes:
            codes.append(c)
    if len(codes) < 2:
        sys.exit("Dame al menos dos códigos de biblioteca.\n\n" + __doc__)
    dest = dest or codes[0]
    if dest not in codes:
        codes.append(dest)

    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    merged_sheets = []
    used_names, used_ids = set(), set()

    for code in codes:
        doc, node = fetch_doc(code)
        if node is not None:
            path = BACKUP_DIR / "biblioteca-{}-{}.json".format(code, stamp)
            path.write_text(json.dumps(node, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        if not doc or not isinstance(doc.get("sheets"), list):
            print("  {}  (vacía o ilegible — se salta)".format(code))
            continue

        print("  {}  {} hoja(s)".format(code, len(doc["sheets"])))
        for sheet in doc["sheets"]:
            if not isinstance(sheet, dict):
                continue
            name = (sheet.get("name") or "Set").strip() or "Set"
            # Nombres repetidos entre bibliotecas: se distinguen por código.
            if name in used_names:
                name = "{} ({})".format(name, code[:5])
                n = 2
                while name in used_names:
                    name = "{} ({}-{})".format(sheet.get("name"), code[:5], n)
                    n += 1
            used_names.add(name)

            sid = sheet.get("id") or ""
            if not sid or sid in used_ids:
                sid = "h{}{}".format(len(used_ids), code[:4])
            used_ids.add(sid)

            rows = [r for r in (sheet.get("rows") or [])
                    if isinstance(r, dict)]
            filled = sum(1 for r in rows
                         if any(str(c).strip() for c in (r.get("cells") or [])))
            merged_sheets.append({**sheet, "id": sid, "name": name})
            print("      · {:<34} {} filas ({} con contenido)".format(
                name[:34], len(rows), filled))

    if not merged_sheets:
        sys.exit("No he encontrado ninguna hoja. ¿Son correctos los códigos?")

    merged = {"activeId": merged_sheets[0]["id"], "sheets": merged_sheets}
    print("\nResultado: {} hojas en la biblioteca «{}»".format(len(merged_sheets), dest))
    print("Copias de seguridad en {}/".format(BACKUP_DIR))

    if not apply_it:
        print("\n(simulación: no se ha escrito nada. Añade --aplicar para hacerlo)")
        return

    # PATCH y no PUT: en este mismo nodo viven `catalog` y `ledger`.
    _request(node_url(dest), method="PATCH", body={
        "data": json.dumps(merged, ensure_ascii=False),
        "updatedAt": int(datetime.now().timestamp() * 1000),
    })
    print("\n✓ Escrito en «{}».".format(dest))
    print("  En cada dispositivo: abre la tabla de tiempos, pulsa «Cambiar código»")
    print("  y pon {} para ver todos los sets.".format(dest))


if __name__ == "__main__":
    main()
