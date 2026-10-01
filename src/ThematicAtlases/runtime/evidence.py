"""Publication text is stored once; decisions reference its content identity."""
import hashlib
from ThematicAtlases.integrations.europe_pmc import PUBLICATION_TEXT_CONTRACT_VERSION


def text_hash(text):
    return hashlib.sha256(str(text or "").encode()).hexdigest()


def reference_text(store, publication_ref, text):
    key = text.get("checkpoint_key") or f"ref:{publication_ref}"
    saved = store.get("publication_text", key)
    publication = ((saved or {}).get("payload") or {}).get("publication") or {}
    digest = text_hash(text.get("text"))
    if not saved or text_hash(publication.get("text")) != digest:
        store.put("publication_text", key, 0, "available" if text.get("text") else "no_data",
                  payload={"contract_version": PUBLICATION_TEXT_CONTRACT_VERSION, "publication": {**{k: v for k, v in text.items() if k != "agentic_curator"},
                           "publication_text_ref": publication_ref}, "records": [],
                           "extraction_complete": True, "extraction_enabled": False})
    return {"contract_version": PUBLICATION_TEXT_CONTRACT_VERSION, "key": key, "sha256": digest}


def referenced_text(store, reference):
    saved = store.get("publication_text", reference.get("key", ""))
    publication = ((saved or {}).get("payload") or {}).get("publication") or {}
    if not saved or text_hash(publication.get("text")) != reference.get("sha256"):
        return None
    return {"text": publication.get("text", ""), "text_source": publication.get("text_source", "none"),
            "full_text_status": publication.get("full_text_status", "unavailable"), "checkpoint_key": reference["key"]}
