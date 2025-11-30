import os
import json
import csv
import requests
from datetime import datetime
import sys
import time

try:
    # IA opcional para enriquecimento automático de descrições de medidas
    from google import genai
except ImportError:
    genai = None

# ==============================================================================
# CONFIGURAÇÕES (V28 - Page Unifier + Visual Label + Big DAX)
# ==============================================================================
NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN_PBI_HUB_INVENTORY")
DATABASE_ID = os.environ.get("NOTION_DATABASE_ID_PBI_HUB_INVENTORY")

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# ==============================================================================
# IA HELPERS - GEMINI (Enriquecimento automático de descrições)
# ==============================================================================
def get_gemini_client():
    """
    Cria o client do Gemini usando variáveis de ambiente (GEMINI_API_KEY ou GOOGLE_API_KEY).
    Se a lib não estiver instalada ou a chave não existir, retorna None.
    """
    if genai is None:
        print("[AVISO] google-genai não instalado. Enriquecimento por IA será ignorado.")
        return None
    try:
        client = genai.Client()
        return client
    except Exception as e:
        print(f"[AVISO] Falha ao criar cliente Gemini: {e}")
        return None


def ai_enrich_measures(structure, project_name, model_name, existing_descriptions):
    """
    Gera descrições humanizadas para medidas via Gemini.
    Só chama a IA para medidas que ainda não possuem descrição em existing_descriptions.
    Retorna um dicionário {measure_name: description}.
    """
    client = get_gemini_client()
    if client is None:
        return {}

    measures = structure.get("measures", [])
    # filtra só as medidas que ainda não têm descrição
    target_measures = [m for m in measures if not existing_descriptions.get(m.get("name", ""), "").strip()]
    total = len(target_measures)
    if total == 0:
        print("[INFO] Todas as medidas já possuem descrição em cache. Nenhuma chamada à IA será feita.")
        return {}

    print(f"--- 1.A Enriquecendo descrições via IA ({total} medidas novas) ---")
    new_descriptions = {}

    for i, m in enumerate(target_measures, start=1):
        dax_snippet = m.get("dax", "")
        name = m.get("name", "")
        table = m.get("table", "")

        prompt = f"""
Você é um consultor sênior de BI ajudando a documentar um modelo de dados em Power BI.

Sua tarefa é escrever uma descrição curta (1 a 2 frases, em português do Brasil), simples e objetiva, que qualquer pessoa de negócio consiga entender, explicando o que a medida faz.

Não invente contexto de negócio. Use apenas:
- o nome da medida,
- o nome da tabela e
- a definição DAX abaixo.

Se o domínio (por exemplo, RH, Finanças, Marketing, Operações etc.) não ficar claro a partir desses elementos, use uma linguagem neutra, sem citar áreas de negócio. Se ele ficar evidente (porque aparece no nome do projeto, da tabela ou da medida), você pode mencioná-lo de forma natural.

Contexto do projeto (apenas como referência, não invente nada além do que estiver claro): {project_name}
Nome da medida: [{name}]
Tabela de medidas: {table}

Definição DAX:
```DAX
{dax_snippet}
```

Na sua resposta:
- Explique o que a medida retorna (contagem, soma, média, taxa, variação etc.).
- Se possível, comente o escopo básico (período, filtros, se considera apenas registros ativos etc.), mas somente se isso estiver evidente no DAX ou nos nomes.

IMPORTANTE:
- Não inclua o código DAX na resposta.
- Não use bullet points, numeração, markdown ou emojis.
- Retorne APENAS o texto da descrição final, em uma ou duas frases.
""".strip()

        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            text = (response.text or "").strip()
        except Exception as e:
            print(f"[AVISO] Falha ao descrever medida {name} ({i}/{total}): {e}")
            text = ""

        new_descriptions[name] = text

        if i % 50 == 0 or i == total:
            print(f"  - IA: {i}/{total} medidas processadas...")

        # Pequeno intervalo para evitar qualquer throttle agressivo
        time.sleep(0.1)

    return new_descriptions


def save_measures_enriched(structure, descriptions_by_name, path="measures_enriched.csv"):
    """
    Salva/atualiza um cache local com as descrições das medidas
    para reaproveitar em execuções futuras.
    Chave de controle = nome da medida.
    """
    fieldnames = ["global_id", "measure_name", "description"]
    try:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for m in structure.get("measures", []):
                gid = m.get("global_id") or ""
                name = m.get("name", "")
                desc = descriptions_by_name.get(name, "")
                writer.writerow({
                    "global_id": gid,
                    "measure_name": name,
                    "description": desc
                })
        print(f"--- Cache de descrições salvo em {path} ({len(structure.get('measures', []))} medidas) ---")
    except Exception as e:
        print(f"[AVISO] Não foi possível salvar {path}: {e}")


# ==============================================================================
# 1. CARREGAMENTO E UNIFICAÇÃO
# ==============================================================================
def load_data():
    print("--- 1. Carregando Dados (V28 + IA + Visual Label) ---")
    if not os.path.exists("pbi_config.json"):
        sys.exit("[ERRO] pbi_config.json ausente.")
    if not os.path.exists("model_structure.json"):
        sys.exit("[ERRO] model_structure.json ausente. Rode o minerador_pbi.py primeiro.")

    with open("pbi_config.json", "r", encoding="utf-8") as f:
        config = json.load(f)
    with open("model_structure.json", "r", encoding="utf-8") as f:
        structure = json.load(f)

    # Flag de controle do enriquecimento por IA (padrão: False se não existir no config)
    use_ai = config.get("use_ai_enrichment", False)
    ai_model = config.get("ai_model", "gemini-2.5-flash")

    # Dicionário mestre de descrições, mapeado por NOME da medida
    descriptions_by_name = {}

    # 1) Tenta reaproveitar descrições existentes de um cache local (measures_enriched.csv)
    if os.path.exists("measures_enriched.csv"):
        try:
            with open("measures_enriched.csv", "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if not row:
                        continue
                    name = (row.get("measure_name") or "").strip()
                    desc = (row.get("description") or "").strip()
                    if name:
                        descriptions_by_name[name] = desc
            print(f"--- Cache de descrições carregado de measures_enriched.csv ({len(descriptions_by_name)} medidas) ---")
        except Exception as e:
            print(f"[AVISO] Falha ao ler measures_enriched.csv, seguirá sem cache: {e}")
            descriptions_by_name = {}
    else:
        print("[INFO] Nenhum measures_enriched.csv encontrado. Cache de descrições começará vazio.")

    # 2) Se IA estiver habilitada, gera/atualiza descrições via Gemini
    if use_ai:
        project_name = config.get("project_name", "")
        ai_desc = ai_enrich_measures(structure, project_name, ai_model, descriptions_by_name)

        # IA tem precedência sobre cache antigo
        for name, desc in ai_desc.items():
            if desc is not None:
                descriptions_by_name[name] = desc
    else:
        print("[INFO] Enriquecimento por IA desabilitado (use_ai_enrichment = false ou ausência no pbi_config.json).")

    # 3) UNIFICAÇÃO INTELIGENTE DE PÁGINAS (COM LABEL DO VISUAL)
    unified_pages = {}

    # 3.1. Base principal: report_structure vindo do Minerador
    raw_pages = structure.get("report_structure", [])
    for p in raw_pages:
        p_name = p.get("name", "Geral")
        if p_name not in unified_pages:
            unified_pages[p_name] = []

        current_ids = {v["id"] for v in unified_pages[p_name]}
        for v in p.get("visuals", []):
            if v["id"] not in current_ids:
                # Garante que existe campo label mesmo que vazio
                unified_pages[p_name].append({
                    "id": v.get("id"),
                    "type": v.get("type", "Visual Desconhecido"),
                    "label": v.get("label", ""),
                    "measures": list(set(v.get("measures", [])))
                })
                current_ids.add(v["id"])

    # 3.2. Fallback / complemento: visuais referenciados pelos detalhes das medidas
    for m in structure.get("measures", []):
        vis_details = m.get("visual_details", [])
        for v in vis_details:
            p_name = v.get("page", "Geral")
            if p_name not in unified_pages:
                unified_pages[p_name] = []

            v_id = v.get("id")
            v_type = v.get("type", "Visual Desconhecido")
            v_label = v.get("label", "")  # pode vir do minerador se mapeado lá

            found = False
            for existing_v in unified_pages[p_name]:
                if existing_v["id"] == v_id:
                    if m["name"] not in existing_v["measures"]:
                        existing_v["measures"].append(m["name"])
                    found = True
                    break

            if not found:
                unified_pages[p_name].append({
                    "id": v_id,
                    "type": v_type,
                    "label": v_label,
                    "measures": [m["name"]]
                })

    # Injeta de volta na estrutura para uso nos builders
    structure["unified_pages"] = unified_pages

    # Enriquece medidas (descrições) usando dicionário por NOME
    for m in structure.get("measures", []):
        m_name = m.get("name", "")
        m["desc"] = descriptions_by_name.get(m_name, "")
        m["visual_text"] = "Sim" if m.get("in_visual") else "Não"

    print(f"> Páginas unificadas para processamento: {len(unified_pages)}")

    # Atualiza / garante measures_enriched.csv SEMPRE (com ou sem IA)
    save_measures_enriched(structure, descriptions_by_name, path="measures_enriched.csv")

    return config, structure


# ==============================================================================
# 2. API HELPERS
# ==============================================================================
def create_inline_db(parent_id, title, properties):
    url = "https://api.notion.com/v1/databases"
    payload = {
        "parent": {"page_id": parent_id},
        "title": [{"type": "text", "text": {"content": title}}],
        "properties": properties,
        "is_inline": True
    }
    try:
        resp = requests.post(url, headers=HEADERS, json=payload)
        data = resp.json()
        if resp.status_code != 200 or "id" not in data:
            print(f"❌ ERRO ao criar database inline '{title}'")
            print("Status:", resp.status_code)
            print("Resposta:", data)
            return None
        return data["id"]
    except Exception as e:
        print(f"[ERRO] Exceção ao criar database inline '{title}': {e}")
        return None


def add_row_heavy(db_id, props, children_blocks, name="Row"):
    url_create = "https://api.notion.com/v1/pages"
    payload_create = {"parent": {"database_id": db_id}, "properties": props}

    page_id = None
    for _ in range(3):
        try:
            r = requests.post(url_create, headers=HEADERS, json=payload_create)
            if r.status_code == 200:
                page_id = r.json()["id"]
                break
            elif r.status_code == 429:
                print(f"[INFO] Notion 429 (rate limit) ao criar linha '{name}'. Aguardando...")
                time.sleep(5)
            else:
                print(f"[ERRO] Notion {r.status_code} ao criar linha '{name}': {r.text}")
                time.sleep(1)
        except Exception as e:
            print(f"[EXC] Exceção ao criar linha '{name}': {e}")
            time.sleep(1)

    if not page_id:
        print(f"❌ Erro ao criar linha: {name}")
        return None

    url_app = f"https://api.notion.com/v1/blocks/{page_id}/children"
    batch = 80
    if children_blocks:
        for i in range(0, len(children_blocks), batch):
            req_batch = children_blocks[i:i + batch]
            for _ in range(3):
                try:
                    r = requests.patch(url_app, headers=HEADERS, json={"children": req_batch})
                    if r.status_code == 200:
                        break
                    elif r.status_code == 429:
                        print(f"[INFO] Notion 429 (rate limit) ao anexar blocks da linha '{name}'. Aguardando...")
                        time.sleep(5)
                    else:
                        print(f"[ERRO] Notion {r.status_code} ao anexar blocks da linha '{name}': {r.text}")
                        time.sleep(1)
                except Exception as e:
                    print(f"[EXC] Exceção ao anexar blocks da linha '{name}': {e}")
                    time.sleep(1)
    return page_id



# Builders de blocos Notion
def mk_p(t):
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [
                {
                    "type": "text",
                    "text": {"content": str(t)[:1900]}
                }
            ]
        }
    }


def mk_code(t):
    """
    Cria um bloco de código suportando textos grandes.
    Quebra o conteúdo em chunks de até ~1900 caracteres
    (limite seguro por rich_text do Notion) sem cortar o DAX.
    """
    if t is None:
        t = ""
    max_chunk = 1900
    chunks = []
    for i in range(0, len(t), max_chunk):
        chunk = t[i:i + max_chunk]
        if not chunk:
            continue
        chunks.append({
            "type": "text",
            "text": {"content": chunk}
        })

    if not chunks:
        chunks.append({
            "type": "text",
            "text": {"content": ""}
        })

    return {
        "object": "block",
        "type": "code",
        "code": {
            "language": "markdown",
            "rich_text": chunks
        }
    }


def mk_head(t, lvl=3):
    if lvl > 3:
        lvl = 3
    return {
        "object": "block",
        "type": f"heading_{lvl}",
        f"heading_{lvl}": {
            "rich_text": [
                {
                    "type": "text",
                    "text": {"content": str(t)[:1900]}
                }
            ]
        }
    }


def mk_li(t):
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {
                    "type": "text",
                    "text": {"content": str(t)[:1900]}
                }
            ]
        }
    }


def mk_div():
    return {"object": "block", "type": "divider", "divider": {}}


def create_table_block(headers, rows):
    tb = {
        "object": "block",
        "type": "table",
        "table": {
            "table_width": len(headers),
            "has_column_header": True,
            "children": []
        }
    }
    tb["table"]["children"].append({
        "type": "table_row",
        "table_row": {
            "cells": [
                [{"type": "text", "text": {"content": str(h)[:1900]}}] for h in headers
            ]
        }
    })
    for r in rows:
        cells = [
            [{"type": "text", "text": {"content": str(c)[:1900]}}] for c in r
        ]
        tb["table"]["children"].append({
            "type": "table_row",
            "table_row": {"cells": cells}
        })
    return tb


def archive_old_entries(project_name):
    print("--- 2. Limpando Notion (arquivando versões antigas do projeto) ---")
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    payload = {"filter": {"property": "Project Name", "title": {"equals": project_name}}}
    try:
        resp = requests.post(url, headers=HEADERS, json=payload)
        data = resp.json()
        for p in data.get("results", []):
            requests.patch(
                f"https://api.notion.com/v1/pages/{p['id']}",
                headers=HEADERS,
                json={"archived": True}
            )
    except Exception as e:
        print(f"[AVISO] Falha ao arquivar entradas antigas no Notion: {e}")


# ==============================================================================
# 3. BUILDER
# ==============================================================================
def build_structure(config, structure):
    print("--- 3. Construindo V28 (Final + IA + Visual Label + Big DAX) ---")

    # Cria a capa do projeto
    url = "https://api.notion.com/v1/pages"

    # Normaliza o project_link: string vazia vira None (null no JSON)
    raw_project_link = config.get("project_link")
    if isinstance(raw_project_link, str):
        raw_project_link = raw_project_link.strip()
        if raw_project_link == "":
            raw_project_link = None

    properties = {
        "Project Name": {
            "title": [
                {
                    "text": {
                        "content": config["project_name"]
                    }
                }
            ]
        },
        "Last Update": {
            "date": {
                "start": datetime.now().strftime("%Y-%m-%d")
            }
        }
    }

    # Só define Project Link se houver valor (evita erro de validação com string vazia)
    if raw_project_link is not None:
        properties["Project Link"] = {"url": raw_project_link}

    payload = {
        "parent": {"database_id": DATABASE_ID},
        "properties": properties
    }

    resp = requests.post(url, headers=HEADERS, json=payload)
    if resp.status_code != 200:
        print("--- ERRO ao criar capa no Notion ---")
        print("Status:", resp.status_code)
        try:
            data = resp.json()
            print("Resposta:", data)
        except Exception:
            print("Resposta bruta:", resp.text)
        sys.exit(1)

    data = resp.json()
    main_id = data["id"]
    print("> Capa criada.")

    unified_pages = structure.get("unified_pages", {})

    # Mapa NomeMedida -> ID global, para usar na coluna "ID Medidas"
    measure_name_to_id = {
        m["name"]: m.get("global_id", "")
        for m in structure.get("measures", [])
    }

    # 1. RELACIONAMENTOS
    print("> DB 1: Relacionamentos")
    db_rel = create_inline_db(main_id, "1. Relacionamentos", {
        "ID": {"title": {}},
        "De": {"rich_text": {}},
        "Para": {"rich_text": {}},
        "Cardinalidade": {"select": {}},
        "Direção": {"select": {}},
        "Ativa?": {"select": {}}
    })
    if db_rel:
        for i, r in enumerate(structure.get("relationships", [])):
            add_row_heavy(
                db_rel,
                {
                    "ID": {"title": [{"text": {"content": f"R{i + 1}"}}]},
                    "De": {"rich_text": [{"text": {"content": r.get("from", "?")}}]},
                    "Para": {"rich_text": [{"text": {"content": r.get("to", "?")}}]},
                    "Cardinalidade": {"select": {"name": r.get("cardinality", "-")}},
                    "Direção": {"select": {"name": r.get("filter", "-")}},
                    "Ativa?": {"select": {"name": r.get("active", "-")}}
                },
                []
            )

    # 2. TABELAS
    print("> DB 2: Tabelas")
    db_tbl = create_inline_db(main_id, "2. Tabelas", {
        "Nome": {"title": {}},
        "Qtd Colunas": {"number": {}},
        "Qtd Col Calculadas": {"number": {}},
        "Qtd Col Físicas": {"number": {}}
    })
    IGNORE = ["_DAX", "_DAX_AUDIT", "DAX", "_TEST"]
    if db_tbl:
        for t_name, t_data in sorted(structure.get("tables", {}).items()):
            if any(ign in t_name for ign in IGNORE):
                continue
            body = []
            cols = t_data.get("columns", [])
            if cols:
                body.append(mk_p(f"Colunas ({len(cols)}):"))
                h = ["Coluna", "Origem", "Tipo"]
                rs = [
                    [c["name"], c.get("origin", "Física"), c["type"]]
                    for c in cols
                ]
                if len(rs) > 90:
                    rs = rs[:90]
                body.append(create_table_block(h, rs))
            total_cols = len(cols)
            calc_cols = sum(1 for c in cols if c.get("origin") == "Calculada (DAX)")
            phys_cols = total_cols - calc_cols

            add_row_heavy(
                db_tbl,
                {
                    "Nome": {"title": [{"text": {"content": t_name}}]},
                    "Qtd Colunas": {"number": total_cols},
                    "Qtd Col Calculadas": {"number": calc_cols},
                    "Qtd Col Físicas": {"number": phys_cols}
                },
                body,
                t_name
            )

    # 3. PÁGINAS (UNIFICADAS, COM VISUAL LABEL + ID Medidas)
    print("> DB 3: Páginas do Relatório (Unified + Label + IDs)")
    db_pg = create_inline_db(main_id, "3. Páginas do Relatório", {
        "Página": {"title": {}},
        "Qtd Visuais": {"number": {}}
    })

    if db_pg:
        for p_name, vis_list in sorted(unified_pages.items()):
            body = [mk_head(f"Visuais nesta página ({len(vis_list)}):", 3)]

            if vis_list:
                # Agora mostramos IDs das medidas, não os nomes
                h = ["Tipo Visual", "Visual Label", "Qtd", "ID Medidas"]
                rs = []
                for v in vis_list:
                    m_names = v.get("measures", [])
                    m_len = len(m_names)

                    # Converte nomes das medidas em IDs globais (M001, M002, ...)
                    m_ids = []
                    for m_name in m_names:
                        mid = measure_name_to_id.get(m_name, "")
                        if mid:
                            m_ids.append(mid)
                    m_str_ids = ", ".join(m_ids)

                    label = v.get("label", "") or ""
                    rs.append([
                        v.get("type", "Visual Desconhecido"),
                        label,
                        str(m_len),
                        m_str_ids
                    ])

                if len(rs) > 90:
                    rs = rs[:90]
                body.append(create_table_block(h, rs))
            else:
                body.append(mk_p("Nenhum visual com medidas detectado."))

            add_row_heavy(
                db_pg,
                {
                    "Página": {"title": [{"text": {"content": p_name}}]},
                    "Qtd Visuais": {"number": len(vis_list)}
                },
                body,
                p_name
            )

    # 4. VISUAIS (Agrupados por Tipo)
    print("> DB 4: Tipos de Visuais")
    db_vis = create_inline_db(main_id, "4. Visuais Detalhados", {
        "Tipo": {"title": {}},
        "Qtd Páginas": {"number": {}}
    })

    type_map = {}
    for p_name, v_list in unified_pages.items():
        for v in v_list:
            vt = v.get("type", "Visual Desconhecido")
            if vt not in type_map:
                type_map[vt] = set()
            type_map[vt].add(p_name)

    if db_vis:
        for v_type, pages in type_map.items():
            body = [mk_head("Presente nas Páginas:", 3)]
            for pg in sorted(list(pages)):
                body.append(mk_li(pg))

            add_row_heavy(
                db_vis,
                {
                    "Tipo": {"title": [{"text": {"content": v_type}}]},
                    "Qtd Páginas": {"number": len(pages)}
                },
                body,
                v_type
            )

    # 5. DAX
    print("> DB 5: Medidas DAX")
    db_dax = create_inline_db(main_id, "5. Medidas DAX", {
        "Nome": {"title": {}},
        "ID": {"rich_text": {}},
        "Status": {"select": {}},
        "Visual?": {"select": {}}
    })

    if db_dax:
        total = len(structure.get("measures", []))
        for i, m in enumerate(structure.get("measures", [])):
            status = m.get("status", "Analise")

            # Sanitiza o nome da medida para evitar erros no Notion
            raw_name = (m.get("name") or "").strip()
            if not raw_name:
                safe_name = f"[Unnamed Measure {m.get('global_id', '')}]".strip()
            else:
                # Evita títulos excessivamente longos
                safe_name = raw_name[:1800]


            body = [
                mk_head("📖 Descrição", 3),
                mk_p(m.get("desc", "")),
                mk_div(),
                mk_head("💻 Código DAX", 3),
                mk_code(m.get("dax", "")),
                mk_div(),
                mk_head("📄 Uso em Visuais", 3)
            ]

            found_in_pages = []
            for p_name, v_list in unified_pages.items():
                for v in v_list:
                    if m["name"] in v.get("measures", []):
                        found_in_pages.append(f"Pág: {p_name} | {v.get('type', 'Visual')} | {v.get('label', '')}")

            if found_in_pages:
                for fp in sorted(list(set(found_in_pages))):
                    body.append(mk_li(fp))
            else:
                body.append(mk_p("Sem uso direto."))

            body.append(mk_div())
            body.append(mk_head("🔗 Pais", 3))
            if m.get("parent_names"):
                for x in m.get("parent_names"):
                    body.append(mk_li(x))
            else:
                body.append(mk_p("-"))

            body.append(mk_head("🌲 Filhos", 3))
            if m.get("child_names"):
                for x in m.get("child_names"):
                    body.append(mk_li(x))
            else:
                body.append(mk_p("-"))

            time.sleep(0.1)
            add_row_heavy(
                db_dax,
                {
                    "Nome": {"title": [{"text": {"content": safe_name}}]},
                    "ID": {"rich_text": [{"text": {"content": m.get("global_id", "")}}]},
                    "Status": {"select": {"name": status}},
                    "Visual?": {"select": {"name": m.get("visual_text", "")}}
                },
                body,
                m["name"]
            )

            if (i + 1) % 50 == 0:
                print(f"  - {i + 1}/{total} medidas enviadas para o Notion...")



    # 6. DAX Tabelas (Colunas Calculadas)
    print("> DB 6: Medidas DAX Tabelas (Colunas Calculadas)")
    db_dax_cols = create_inline_db(main_id, "6. Medidas DAX Tabelas", {
        "Nome Coluna": {"title": {}},
        "Tabela": {"rich_text": {}}
    })

    if db_dax_cols:
        for t_name, t_data in sorted(structure.get("tables", {}).items()):
            cols = t_data.get("columns", [])
            for c in cols:
                if c.get("origin") != "Calculada (DAX)":
                    continue
                expr = (c.get("expression_dax") or "").strip()
                body = [
                    mk_head("Tabela", 3),
                    mk_p(t_name),
                    mk_div(),
                    mk_head("Código DAX", 3),
                    mk_code(expr or "// Expressão DAX não capturada automaticamente.")
                ]
                add_row_heavy(
                    db_dax_cols,
                    {
                        "Nome Coluna": {"title": [{"text": {"content": c.get("name", "")}}]},
                        "Tabela": {"rich_text": [{"text": {"content": t_name}}]}
                    },
                    body,
                    f"{t_name}.{c.get('name', '')}"
                )

    # 7. Conexões DB
    print("> DB 7: Conexões DB")
    db_conn = create_inline_db(main_id, "7. Conexões DB", {
        "Nome Tabela": {"title": {}},
        "Fonte": {"rich_text": {}},
        "Projeto / Servidor": {"rich_text": {}},
        "Dataset / Schema": {"rich_text": {}},
        "Objeto": {"rich_text": {}}
    })

    if db_conn:
        for conn in structure.get("connections", []):
            t_name = conn.get("table", "")
            fonte = conn.get("source_type", "")
            projeto = conn.get("project", "")
            dataset = conn.get("dataset", "")
            obj = conn.get("object", "")
            m_expr = (conn.get("m_expression") or "").strip()

            body = [
                mk_head("Detalhes da Conexão", 3),
                mk_p(f"Fonte: {fonte}"),
                mk_p(f"Projeto/Servidor: {projeto}"),
                mk_p(f"Dataset/Schema: {dataset}"),
                mk_p(f"Objeto: {obj}"),
                mk_div(),
                mk_head("M Code (Consulta)", 3),
                mk_code(m_expr or "// M code não capturado automaticamente.")
            ]

            add_row_heavy(
                db_conn,
                {
                    "Nome Tabela": {"title": [{"text": {"content": t_name}}]},
                    "Fonte": {"rich_text": [{"text": {"content": fonte}}]},
                    "Projeto / Servidor": {"rich_text": [{"text": {"content": projeto}}]},
                    "Dataset / Schema": {"rich_text": [{"text": {"content": dataset}}]},
                    "Objeto": {"rich_text": [{"text": {"content": obj}}]}
                },
                body,
                t_name or fonte
            )

    # 8. RLS (Row-Level Security)
    print("> DB 8: RLS (Row-Level Security)")
    db_rls = create_inline_db(main_id, "8. RLS", {
        "Role Name": {"title": {}},
        "Qtd Tabelas": {"number": {}}
    })

    roles = structure.get("roles", [])
    if db_rls and roles:
        for role in roles:
            rname = role.get("name", "")
            tables = role.get("tables", [])
            body = [mk_head("Tabelas e Regras", 3)]
            if tables:
                for t in tables:
                    tname = t.get("table", "")
                    fdax = (t.get("filter_dax") or "").strip()
                    body.append(mk_head(tname, 3))
                    if fdax:
                        body.append(mk_code(fdax))
                    else:
                        body.append(mk_p("Sem filtro definido."))
            else:
                body.append(mk_p("Role sem tabelas associadas."))

            add_row_heavy(
                db_rls,
                {
                    "Role Name": {"title": [{"text": {"content": rname}}]},
                    "Qtd Tabelas": {"number": len(tables)}
                },
                body,
                rname
            )
    print("\n✨ SUCESSO TOTAL! ✨")


if __name__ == "__main__":
    conf, struct = load_data()
    archive_old_entries(conf["project_name"])
    build_structure(conf, struct)
