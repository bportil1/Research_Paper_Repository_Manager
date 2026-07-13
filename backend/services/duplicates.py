from difflib import SequenceMatcher
from backend.utils.text import normalize_title

def title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_title(a), normalize_title(b)).ratio()

def find_duplicate_groups(rows):
    groups=[]; used=set()
    for i,a in enumerate(rows):
        if a.get("PaperID") in used: continue
        group=[a]
        for b in rows[i+1:]:
            same_hash=a.get("SHA256") and a.get("SHA256")==b.get("SHA256")
            same_doi=a.get("DOI") and a.get("DOI","").lower()==b.get("DOI","").lower()
            sim=title_similarity(a.get("Title",""),b.get("Title",""))
            if same_hash or same_doi or (sim>=.94 and "title not found" not in normalize_title(a.get("Title",""))): group.append({**b,"Similarity":round(sim,3)})
        if len(group)>1: groups.append(group); used.update(r.get("PaperID") for r in group)
    return groups
