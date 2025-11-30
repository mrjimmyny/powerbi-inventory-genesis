import os
import requests
import time
import json

"""
Script: notion_post_links_ids.py

Objetivo
--------
Pós-processar o HUB de Documentação no Notion para transformar todos os IDs de medidas
(M001, M002, ...) que aparecem na coluna "ID Medidas" do banco:

    3. Páginas do Relatório (Unified + Label + IDs)

em links clicáveis que apontam diretamente para as páginas das medidas no banco:

    5. Medidas DAX

Uso
---
1. Certifique-se de que o constructor_notion.py já rodou com sucesso e criou
   todos os bancos (especialmente 3. Páginas do Relatório e 5. Medidas DAX).
2. Ajuste o NOTION_TOKEN abaixo se necessário.
3. Rode este script uma única vez após o constructor.

Obs.: Este script é totalmente opcional. Se não quiser links clicáveis, basta não rodá-lo.
"""

# ==============================================================================
# CONFIGURAÇÕES - REUTILIZANDO O MESMO TOKEN DO CONSTRUCTOR
# ==============================================================================

NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN_PBI_HUB_INVENTORY")

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

# Nomes exatos dos bancos criados pelo constructor
DB5_NAME = "5. Medidas DAX"
DB3_NAME = "3. Páginas do Relatório"


# ==============================================================================
# HELPERS NOTION
# ==============================================================================

def notion_post(url, payload):
    for _ in range(3):
        r = requests.post(url, headers=HEADERS, json=payload)
        if r.status_code == 429:
            time.sleep(5)
            continue
        if r.status_code in (200, 400, 404):
            return r
        time.sleep(1)
    return r


def notion_get(url, params=None):
    for _ in range(3):
        r = requests.get(url, headers=HEADERS, params=params or {})
        if r.status_code == 429:
            time.sleep(5)
            continue
        if r.status_code in (200, 400, 404):
            return r
        time.sleep(1)
    return r


def notion_patch(url, payload):
    for _ in range(3):
        r = requests.patch(url, headers=HEADERS, json=payload)
        if r.status_code == 429:
            time.sleep(5)
            continue
        if r.status_code in (200, 400, 404):
            return r
        time.sleep(1)
    return r


# ==============================================================================
# 1) LOCALIZAR DATABASES PELO TÍTULO
# ==============================================================================

def search_database_by_title(title: str) -> str:
    """
    Procura um database Notion pelo título (name) usando /v1/search.
    Retorna o ID do database ou None se não encontrar.
    """
    url = "https://api.notion.com/v1/search"
    payload = {
        "query": title,
        "filter": {"property": "object", "value": "database"},
    }
    r = notion_post(url, payload)
    if r.status_code != 200:
        print(f"❌ Erro ao buscar database '{title}': {r.status_code} - {r.text}")
        return None

    data = r.json()
    for res in data.get("results", []):
        db_title = res.get("title", [])
        plain = "".join([t["plain_text"] for t in db_title if t.get("plain_text")])
        if plain.strip() == title.strip():
            return res["id"]

    print(f"⚠️ Database '{title}' não encontrado via search.")
    return None


# ==============================================================================
# 2) QUERY PAGINADO EM DATABASE
# ==============================================================================

def query_all_pages(db_id: str):
    """
    Faz query paginada em um database Notion, retornando todas as páginas.
    """
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    all_results = []
    payload = {}
    while True:
        r = notion_post(url, payload)
        if r.status_code != 200:
            print(f"❌ Erro ao consultar database {db_id}: {r.status_code} - {r.text}")
            break
        data = r.json()
        all_results.extend(data.get("results", []))
        nxt = data.get("next_cursor")
        if not nxt:
            break
        payload["start_cursor"] = nxt
    return all_results


# ==============================================================================
# 3) MAPA ID MEDIDA -> URL PÁGINA (DB 5 - Medidas DAX)
# ==============================================================================

def build_measure_id_to_url_map(db5_id: str):
    """
    Lê o database '5. Medidas DAX' e monta um mapa:
        { "M001": "https://www.notion.so/..." , ... }
    usando a propriedade "ID" e o campo "url" de cada página.
    """
    pages = query_all_pages(db5_id)
    mapping = {}

    print(f"🔎 Construindo mapa ID -> URL a partir de {len(pages)} medidas...")

    for page in pages:
        props = page.get("properties", {})
        id_prop = props.get("ID", {})
        rich = id_prop.get("rich_text", [])
        if not rich:
            continue
        measure_id = rich[0].get("plain_text", "").strip()
        if not measure_id:
            continue

        url = page.get("url", "").strip()
        if not url:
            # fallback: usa page_id se não houver url
            pid = page.get("id", "")
            if pid:
                clean = pid.replace("-", "")
                url = f"https://www.notion.so/{clean}"

        if url:
            mapping[measure_id] = url

    print(f"✅ Mapa ID->URL montado com {len(mapping)} entradas.")
    return mapping


# ==============================================================================
# 4) ATUALIZAR TABELAS DO DB 3 COM LINKS
# ==============================================================================

def get_block_children(block_id: str):
    """
    Lê todos os filhos de um bloco (paginação se necessário).
    """
    url = f"https://api.notion.com/v1/blocks/{block_id}/children"
    children = []
    params = {"page_size": 100}
    while True:
        r = notion_get(url, params)
        if r.status_code != 200:
            print(f"❌ Erro ao carregar filhos do bloco {block_id}: {r.status_code} - {r.text}")
            break
        data = r.json()
        children.extend(data.get("results", []))
        nxt = data.get("next_cursor")
        if not nxt:
            break
        params["start_cursor"] = nxt
    return children


def build_linked_rich_text(original_text: str, id_to_url: dict):
    """
    Recebe o texto de uma célula (ex: 'M001, M002, M010') e devolve uma lista
    de rich_text segments com links quando tivermos URL para o ID.
    """
    text = original_text or ""
    text = text.strip()
    if not text:
        return []

    parts = [p.strip() for p in text.split(",") if p.strip()]
    rich_segments = []

    for i, token in enumerate(parts):
        url = id_to_url.get(token)
        seg = {
            "type": "text",
            "text": {
                "content": token,
            },
        }
        if url:
            seg["text"]["link"] = {"url": url}

        rich_segments.append(seg)

        # adiciona a vírgula/space entre os IDs, se não for o último
        if i < len(parts) - 1:
            rich_segments.append({
                "type": "text",
                "text": {
                    "content": ", "
                }
            })

    return rich_segments


def update_db3_with_links(db3_id: str, id_to_url: dict):
    """
    Para cada página do DB 3 (Páginas do Relatório), localiza a tabela com ID Medidas,
    e substitui o texto da última coluna por versões clicáveis baseadas em id_to_url.
    """
    pages = query_all_pages(db3_id)
    print(f"🔎 Atualizando links em {len(pages)} páginas de '3. Páginas do Relatório'...")

    for p in pages:
        page_id = p.get("id")
        title_prop = p.get("properties", {}).get("Página", {})
        title_rt = title_prop.get("title", [])
        page_name = "".join([t.get("plain_text", "") for t in title_rt]) or page_id
        print(f"  > Página: {page_name}")

        # 1) Pega todos os blocos da página
        page_children = get_block_children(page_id)
        # 2) Procura blocos do tipo 'table'
        table_blocks = [b for b in page_children if b.get("type") == "table"]
        if not table_blocks:
            print("    - Nenhuma tabela encontrada, pulando.")
            continue

        for tbl in table_blocks:
            tbl_id = tbl["id"]
            # 3) Carrega as linhas da tabela
            rows = get_block_children(tbl_id)
            if not rows:
                continue

            # primeira linha = header, não mexemos
            for row in rows[1:]:
                if row.get("type") != "table_row":
                    continue
                tr = row["table_row"]
                cells = tr.get("cells", [])
                if not cells:
                    continue

                # assumimos que a última coluna é "ID Medidas"
                last_idx = len(cells) - 1
                cell = cells[last_idx]
                # cell é uma lista de rich_text
                if not cell:
                    continue

                # Concatena todo texto plain_text atual
                original_text = "".join([rt.get("plain_text", rt.get("text", {}).get("content", "")) for rt in cell])

                if not original_text.strip():
                    continue

                # Monta novos segments com links
                new_rich = build_linked_rich_text(original_text, id_to_url)
                if not new_rich:
                    continue

                cells[last_idx] = new_rich

                # 4) Atualiza a linha
                payload = {
                    "table_row": {
                        "cells": cells
                    }
                }
                url = f"https://api.notion.com/v1/blocks/{row['id']}"
                r = notion_patch(url, payload)
                if r.status_code != 200:
                    print(f"    ❌ Erro ao atualizar linha da tabela: {r.status_code} - {r.text}")
                else:
                    print(f"    ✅ IDs atualizados na linha da tabela.")

    print("✅ Atualização de links em DB 3 concluída.")


# ==============================================================================
# MAIN
# ==============================================================================

def main():
    print("=== Script pós-processamento: Links em ID Medidas (DB 3) ===")

    # 1) Localiza DB 5 (Medidas DAX)
    db5_id = search_database_by_title(DB5_NAME)
    if not db5_id:
        print("❌ Não foi possível localizar o database '5. Medidas DAX'. Encerrando.")
        return

    # 2) Monta mapa ID -> URL
    id_to_url = build_measure_id_to_url_map(db5_id)
    if not id_to_url:
        print("⚠️ Nenhum ID de medida encontrado em '5. Medidas DAX'. Nada para linkar.")
        return

    # 3) Localiza DB 3 (Páginas do Relatório)
    db3_id = search_database_by_title(DB3_NAME)
    if not db3_id:
        print("❌ Não foi possível localizar o database '3. Páginas do Relatório'. Encerrando.")
        return

    # 4) Atualiza as tabelas do DB 3 com links clicáveis
    update_db3_with_links(db3_id, id_to_url)

    print("=== Fim do script. ===")


if __name__ == "__main__":
    main()
