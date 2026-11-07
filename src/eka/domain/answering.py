"""Fixed strings of the answering flow, shared by the service and the adapters."""

# What the model must reply, and nothing else, when the passages do not contain the answer.
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
# Present in the system prompt of the follow-up rewrite request (and absent from answer prompts).
REWRITE_MARKER = "REWRITE_TASK"

REFUSAL_TEXT = "I could not find this in your documents."
UNVERIFIED_TEXT = (
    "I could not produce an answer whose citations I could verify. "
    "Please rephrase the question or check the documents directly."
)

# Reasons stored with a refused answer. Fixed codes, safe to show.
REASON_WEAK_EVIDENCE = "weak_evidence"
REASON_NO_PASSAGES = "no_passages"
REASON_MODEL_DECLINED = "model_declined"
REASON_UNVERIFIED = "unverified_citations"
