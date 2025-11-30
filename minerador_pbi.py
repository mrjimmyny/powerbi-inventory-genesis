import os
import re
import json
import csv

# ==============================================================================
# CONFIGURAÇÃO
# ==============================================================================
TMDL_EXT = ".tmdl"

# Dicionário de Tradução de Visuais (Técnico -> Humano)
VISUAL_TRANSLATE = {
    "card": "Cartão (Card)",
    "multiRowCard": "Cartão Multi-Linha",
    "slicer": "Segmentação de Dados (Slicer)",
    "pivotTable": "Matriz (Matrix)",
    "tableEx": "Tabela",
    "clusteredBarChart": "Gráfico de Barras Clusterizado",
    "clusteredColumnChart": "Gráfico de Colunas Clusterizado",
    "lineChart": "Gráfico de Linha",
    "areaChart": "Gráfico de Área",
    "pieChart": "Gráfico de Pizza",
    "donutChart": "Gráfico de Rosca",
    "scatterChart": "Gráfico de Dispersão",
    "gauge": "Gauge (Velocímetro)",
    "map": "Mapa",
    "filledMap": "Mapa Preenchido",
    "treemap": "Treemap",
    "waterfallChart": "Cascata",
    "basicShape": "Forma Básica",
    "textBox": "Caixa de Texto",
    "image": "Imagem"
}

def clean_name(raw_name):
    """Normaliza nomes de tabelas/medidas/colunas vindos do TMDL."""
    if not raw_name:
        return ""
    if "=" in raw_name:
        raw_name = raw_name.split('=')[0]
    if "lineageTag" in raw_name:
        raw_name = raw_name.split("lineageTag")[0]
    raw_name = raw_name.strip()
    if len(raw_name) >= 2 and raw_name[0] in "'`" and raw_name[-1] == raw_name[0]:
        raw_name = raw_name[1:-1]
    return raw_name.replace('"', '').replace("'", '').replace('`', '').strip()

def clean_ref(ref):
    return ref.replace("'", "").replace('"', "").strip()

def get_human_visual_type(raw_type):
    """Traduz tipos técnicos para legíveis"""
    if not raw_type:
        return "Visual Desconhecido"
    return VISUAL_TRANSLATE.get(raw_type, raw_type)

# --- SCANNER V31 (Smart Type Detection) ---
def scan_report_hierarchy_v31(root_path, all_measures_names):
    print(f"--- 🕵️  Mapeando Hierarquia (V31 Visual Decoder) ---")
    
    # 1. Mapeia Páginas
    page_map = {}
    for dirpath, _, filenames in os.walk(root_path):
        for f in filenames:
            if f.lower().endswith(".json"):
                try:
                    with open(os.path.join(dirpath, f), "r", encoding="utf-8-sig") as file:
                        data = json.load(file)
                        if "sections" in data:
                            for s in data["sections"]:
                                if "name" in s and "displayName" in s:
                                    page_map[s["name"]] = s["displayName"]
                        if "name" in data and "displayName" in data:
                            page_map[data["name"]] = data["displayName"]
                            page_map[os.path.basename(dirpath)] = data["displayName"]
                except:
                    pass
    
    print(f"   > Páginas identificadas: {len(page_map)}")

    pages_db = {}
    files_scanned = 0

    # 2. Varredura
    for dirpath, _, filenames in os.walk(root_path):
        if "SemanticModel" in dirpath:
            continue

        for filename in filenames:
            if not filename.lower().endswith(".json"):
                continue
            
            # Filtro estrito para pegar apenas arquivos de configuração visual
            is_visual_file = "visual" in filename.lower() or "visuals" in dirpath.lower()
            if not is_visual_file:
                continue

            filepath = os.path.join(dirpath, filename)
            files_scanned += 1
            
            # A. Identifica Página
            page_name = "Geral"
            page_id = "unk"
            path_parts = os.path.normpath(filepath).split(os.sep)
            for part in reversed(path_parts):
                if part in page_map:
                    page_id = part
                    page_name = page_map[part]
                    break
            
            if page_id not in pages_db:
                pages_db[page_id] = {"id": page_id, "name": page_name, "visuals": []}

            # B. Lê Conteúdo
            try:
                with open(filepath, "r", encoding="utf-8-sig") as f:
                    file_content = f.read()
            except:
                continue
            
            lower_content = file_content.lower()

            # C. Busca Medidas
            measures_found = []
            for m in all_measures_names:
                m_lower = m.lower()
                if (
                    f'"{m_lower}"' in lower_content
                    or f"'{m_lower}'" in lower_content
                    or f"[{m_lower}]" in lower_content
                ):
                    measures_found.append(m)
            
            # D. Identifica Tipo de Visual (Lógica Melhorada)
            if measures_found:
                vis_type = "Visual Genérico"
                vis_id_short = os.path.basename(dirpath)  # ID da pasta é mais seguro que do arquivo
                
                # Tentativa 1: Regex específico para visType/visualType
                type_match = re.search(r'"(?:visType|visualType)"\s*:\s*"([^"]+)"', file_content)
                
                if type_match:
                    vis_type = get_human_visual_type(type_match.group(1))
                else:
                    # Tentativa 2: Varredura de Palavras-Chave conhecidas no arquivo
                    for key, human_name in VISUAL_TRANSLATE.items():
                        if f'"{key}"' in file_content:
                            vis_type = human_name
                            break
                
                # Adiciona / consolida visual

                # Tenta capturar Visual Label (título) do visual.json
                vis_label = ""
                try:
                    data_json = json.loads(file_content)
                    visual_obj = (data_json.get("visual") or {})
                    vco = (visual_obj.get("visualContainerObjects") or {})
                    title_objs = vco.get("title") or []
                    for obj in title_objs:
                        lit = (((obj.get("properties") or {}).get("text") or {}).get("expr") or {}).get("Literal", {})
                        v_raw = lit.get("Value")
                        if isinstance(v_raw, str) and v_raw:
                            v_str = v_raw.strip()
                            if v_str.startswith("'") and v_str.endswith("'") and len(v_str) >= 2:
                                v_str = v_str[1:-1]
                            vis_label = v_str
                            break
                except Exception:
                    vis_label = ""

                existing = next((v for v in pages_db[page_id]["visuals"] if v["id"] == vis_id_short), None)
                if existing:
                    existing["measures"] = list(set(existing["measures"] + measures_found))
                    if not existing.get("label") and vis_label:
                        existing["label"] = vis_label
                else:
                    pages_db[page_id]["visuals"].append({
                        "id": vis_id_short,
                        "type": vis_type,
                        "measures": measures_found,
                        "label": vis_label
                    })

    total_vis = sum(len(p["visuals"]) for p in pages_db.values())
    print(f"   > Visuais DECODIFICADOS: {total_vis}")
    return list(pages_db.values()), total_vis

def parse_tmdl_structure(root_path):
    print(f"--- ⛏️  Iniciando Mineração V31 ---")
    tables_data = {}
    relationships = []
    measures = []
    connections = []
    roles = []  # Infra de RLS (preenchido em projetos com roles)

    re_table = re.compile(r"^\s*table\s+['\"]?([^'\"]+)['\"]?", re.MULTILINE)
    re_measure = re.compile(r"measure\s+(['\"]?.*?['\"]?)\s*=")
    re_rel_block = re.compile(
        r"relationship\s+.*?(?=\n\s*(?:relationship|table|measure|\Z))",
        re.DOTALL | re.IGNORECASE,
    )

    for dirpath, _, filenames in os.walk(root_path):
        for filename in filenames:
            if not filename.endswith(TMDL_EXT):
                continue
            filepath = os.path.join(dirpath, filename)
            try:
                with open(filepath, "r", encoding="utf-8-sig") as f:
                    content = f.read()
            except:
                continue
            
            current_table = "Model"
            if "tables" in dirpath:
                t_match = re_table.search(content)
                raw = t_match.group(1) if t_match else filename.replace(TMDL_EXT, "")
                current_table = clean_name(raw)
                if current_table not in tables_data:
                    tables_data[current_table] = {"columns": []}
                
                lines = content.split('\n')
                curr_col = None
                for line in lines:
                    strip = line.strip()
                    if strip.startswith("column "):
                        if curr_col:
                            tables_data[current_table]["columns"].append(curr_col)
                        raw_c = strip.replace("column ", "")
                        is_calc = "=" in raw_c
                        c_name = clean_name(raw_c.split('=')[0])
                        curr_col = {
                            "name": c_name,
                            "type": "string",
                            "origin": "Calculada (DAX)" if is_calc else "Física",
                        }
                    elif curr_col and strip.startswith("dataType:"):
                        curr_col["type"] = strip.replace("dataType:", "").strip()
                if curr_col:
                    tables_data[current_table]["columns"].append(curr_col)

                # Captura opcional de expressão DAX para colunas calculadas
                try:
                    expr_pattern = re.compile(r"column\s+(['\"]?.*?['\"]?)\s*=")
                    col_exprs = {}
                    for m_expr in expr_pattern.finditer(content):
                        raw_name = m_expr.group(1)
                        col_name = clean_name(raw_name)
                        start_expr = m_expr.end()
                        rest_expr = content[start_expr:]
                        nx_expr = re.search(r"\n\s*(?:column|measure|table)\s", rest_expr)
                        end_expr = start_expr + nx_expr.start() if nx_expr else len(content)
                        expr_text = rest_expr[: nx_expr.start()] if nx_expr else rest_expr
                        expr_text = expr_text.strip()
                        col_exprs[col_name] = expr_text

                    for col in tables_data[current_table]["columns"]:
                        if col.get("origin") == "Calculada (DAX)":
                            expr_text = col_exprs.get(col["name"])
                            if expr_text:
                                col["expression_dax"] = expr_text
                except Exception:
                    # Em caso de falha no parsing, seguimos só com metadados básicos
                    pass

                # Captura dados de conexão / origem (M code) para a tabela atual
                try:
                    src_match = re.search(r"source\s*=\s*let(.*?)in\s+(.*)", content, re.DOTALL | re.IGNORECASE)
                    if src_match and current_table:
                        m_block = src_match.group(0)
                        src_body = src_match.group(1)

                        # Tipo de fonte (primeira linha após 'Source =')
                        src_type = ""
                        m_src_type = re.search(r"Source\s*=\s*([^,\n]+)", m_block)
                        if m_src_type:
                            src_type = m_src_type.group(1).strip()

                        # Projeto / servidor (Name="...")
                        project = ""
                        m_proj = re.search(r"Source\{\[Name=\"([^\"]+)\"\]\}\[Data\]", m_block)
                        if m_proj:
                            project = m_proj.group(1).strip()

                        # Dataset / schema
                        dataset = ""
                        m_schema = re.search(r"Name=\"([^\"]+)\",Kind=\"Schema\"", m_block)
                        if m_schema:
                            dataset = m_schema.group(1).strip()

                        # Objeto (View/Table)
                        obj_name = ""
                        m_obj = re.search(r"Name=\"([^\"]+)\",Kind=\"(View|Table)\"", m_block)
                        if m_obj:
                            obj_name = m_obj.group(1).strip()

                        conn = {
                            "table": current_table,
                            "source_type": src_type,
                            "project": project,
                            "dataset": dataset,
                            "object": obj_name,
                            "m_expression": m_block.strip()
                        }
                        tables_data.setdefault(current_table, {}).setdefault("connection", conn)
                        connections.append(conn)
                except Exception:
                    # Em caso de falha na detecção de conexão, ignoramos silenciosamente
                    pass

            fb_table = current_table if current_table else "System"
            for match in re_measure.finditer(content):
                name = clean_name(match.group(1))
                start = match.start()
                rest = content[start + 1 :]
                nx = re.search(r"\n\s*(measure|column|table)\s", rest)
                end = (start + 1 + nx.start()) if nx else len(content)
                measures.append({"name": name, "table": fb_table, "dax": content[start:end]})

            for r in re_rel_block.finditer(content):
                b = r.group(0)
                fc = re.search(r"fromColumn:\s*(.*)", b)
                tc = re.search(r"toColumn:\s*(.*)", b)
                card = re.search(r"cardinality:\s*(\w+)", b)
                filt = re.search(r"crossFilteringBehavior:\s*(\w+)", b)
                act = re.search(r"isActive:\s*(false)", b)
                if fc and tc:
                    relationships.append({
                        "from": clean_ref(fc.group(1)),
                        "to": clean_ref(tc.group(1)),
                        "cardinality": clean_ref(card.group(1)) if card else "OneToMany",
                        "filter": clean_ref(filt.group(1)) if filt else "Single",
                        "active": "False" if act else "True",
                    })

    unique_rels = [dict(t) for t in {tuple(d.items()) for d in relationships}]
    print(f"> Tabelas: {len(tables_data)} | Rels: {len(unique_rels)} | Medidas: {len(measures)} | Conexões: {len(connections)}")
    return {
        "tables": tables_data,
        "relationships": unique_rels,
        "measures": measures,
        "connections": connections,
        "roles": roles
    }

def analyze_and_map(inventory, root_path):
    print("--- 🧠 Cruzando Dados (V31) ---")
    all_names = {m["name"] for m in inventory["measures"]}
    
    # SCAN V31
    report_structure, total_vis = scan_report_hierarchy_v31(root_path, all_names)
    inventory["report_structure"] = report_structure
    
    measure_to_visuals = {m: [] for m in all_names}
    for page in report_structure:
        for vis in page["visuals"]:
            for m_in_vis in vis["measures"]:
                measure_to_visuals[m_in_vis].append({
                    "page": page["name"],
                    "type": vis["type"],
                    "id": vis["id"],
                })

    enhanced = []
    for i, m in enumerate(inventory["measures"]):
        m["global_id"] = f"M{str(i+1).zfill(3)}"
        parents = []
        for other in all_names:
            if other == m["name"]:
                continue
            if re.search(
                r'\[\s*' + re.escape(other) + r'\s*\]|"\s*' + re.escape(other) + r'\s*"',
                m["dax"],
                re.IGNORECASE,
            ):
                parents.append(other)
        m["parent_names"] = parents
        m["visual_details"] = measure_to_visuals.get(m["name"], [])
        m["in_visual"] = len(m["visual_details"]) > 0
        enhanced.append(m)
    
    candidates = 0
    for m in enhanced:
        children = [c["name"] for c in enhanced if m["name"] in c["parent_names"]]
        m["child_names"] = children
        if (not m["parent_names"]) and (not children) and (not m["in_visual"]):
            m["status"] = "Delete Candidate"
            candidates += 1
        elif m["in_visual"]:
            m["status"] = "Visual"
        elif children:
            m["status"] = "Base Cálculo"
        else:
            m["status"] = "Dependente"

    print(f"--- 🧹 Delete Candidates: {candidates} ---")
    inventory["measures"] = enhanced
    return inventory

def save_outputs(inv):
    with open("model_structure.json", "w", encoding="utf-8") as f:
        json.dump(inv, f, indent=4)
    with open("measures_for_ai.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["global_id", "measure_name", "dax_code"])
        for m in inv["measures"]:
            dax_c = re.sub(r"\s+", " ", m["dax"]).replace('"', "'")[:1000]
            writer.writerow([m["global_id"], m["name"], dax_c])

if __name__ == "__main__":
    data = analyze_and_map(parse_tmdl_structure(os.getcwd()), os.getcwd())
    save_outputs(data)
    print("\n✅ MINERADOR V31 CONCLUÍDO.")
