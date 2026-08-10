from __future__ import annotations
import re
from pathlib import Path
from reference_manager.utils.text import is_missing_title

def extract_pdf_metadata(path: Path) -> dict[str, str]:
    import fitz
    doc = fitz.open(path); meta = doc.metadata or {}
    title = str(meta.get("title", "") or "").strip()
    title = title if not is_missing_title(title) else ""
    authors = str(meta.get("author", "") or "").strip()
    keywords = str(meta.get("keywords", "") or "").strip()
    subject = str(meta.get("subject", "") or "").strip()
    if len(doc):
        page = doc[0]; page_height = float(page.rect.height or 792); candidates=[]
        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                spans=line.get("spans", []); text=" ".join(str(s.get("text","")).strip() for s in spans).strip(); text=re.sub(r"\s+"," ",text)
                if not text or len(text)<6: continue
                low=text.lower().strip(" :.-")
                if low in {"abstract","introduction","keywords","contents"} or low.startswith(("arxiv:","doi:","http://","https://")): continue
                size=max([float(s.get("size",0) or 0) for s in spans] or [0]); y=min([float((s.get("bbox") or [0,page_height,0,page_height])[1]) for s in spans] or [page_height])
                if y <= page_height*.48 and size>=8: candidates.append((size,y,text))
        if candidates:
            candidates.sort(key=lambda x:(-x[0],x[1])); max_size=candidates[0][0]; likely=sorted([x for x in candidates if x[0]>=max_size*.82], key=lambda x:x[1]); parts=[]
            for _,_,candidate in likely:
                if candidate not in parts: parts.append(candidate)
                if len(" ".join(parts))>=350: break
            inferred=" ".join(parts).strip()[:500]
            if inferred and not is_missing_title(inferred): title=inferred
        if not title:
            lines=[re.sub(r"\s+"," ",x).strip() for x in page.get_text("text").splitlines()]
            lines=[x for x in lines if len(x)>=8 and x.lower() not in {"abstract","introduction"}]
            if lines: title=" ".join(lines[:2])[:500]
    return {"Title":title,"Authors":authors,"Keywords":keywords,"Abstract":subject}
