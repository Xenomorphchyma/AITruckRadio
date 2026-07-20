# Offline dialogue regression corpus

`radio_dialogues.json` is deliberately a local, deterministic contract corpus.
Every case supplies the runtime context, the canned completion returned by
`FakeLMStudioClient`, and acceptance criteria for the final text after the
normal LM Studio cleanup path.

To add a case, keep it self-contained: include only public context fields used
by the prompt, an output under `raw_response`, and a short `expects` contract.
Use `forbidden_facts` for assertions that a specific unsupported claim must not
reach air; this is safer and clearer than a vague fact-checking heuristic.

Speaker-like `Name:` prefixes are rejected before dialogue parsing.  Content
labels can be listed in `allowed_content_labels`; signs present in
`context.horoscope_expected` are allowed automatically.  Generic appeals to
authority (for example, “experts claim” or “according to …”) must be grounded
in a factual context field such as `news_text`, `weather_text`, track profiles,
or evidence/source fields.  A case may explicitly permit them with
`allowed_authority_claims` or `allowed_authority_sources`; custom factual fields
can be named in `authority_context_fields`.

The suite never starts LM Studio, sends an HTTP request, fetches weather/news,
or initializes an OmniVoice backend.
