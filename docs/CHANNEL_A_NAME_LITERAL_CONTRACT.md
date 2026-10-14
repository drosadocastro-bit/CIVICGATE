# Channel A R1 follow-up: explicit name literals

This prospective intake contract replaces R1's inferred uppercase/proper-name
erasure. Capitalization, a legal suffix, matching proposal arguments and model
confidence do not establish that arbitrary text is a recipient or agency name.

A recognized factual-read clause may contain a labeled name value:

- `recipient "Example Foundation"`
- `agency named "Department of Energy"`
- `destinatario llamado "Cooperativa El Niño"`

Labels are recipient, agency, destinatario and agencia, case-insensitive.
An optional named/called/llamado/llamada marker and the value are separated by
ASCII horizontal whitespace. The value is one valid JSON double-quoted string,
using the existing Text schema (stripped, 1–200 characters). Decoded control,
format, surrogate and other Unicode C-category characters are rejected. Invalid,
unclosed, single/smart-quoted and unlabeled literals do not grant permission.

Only this explicit name value is treated as lookup data by the independent
request-scope signal. Every word outside it still passes the complete-clause read
grammar. Trailing commands, mixed requests and unsupported syntax require review.
The unchanged hard-denial detector examines the entire original request and
proposal first, including literal values; no lexical DENY exception is added.
The literal parser also applies that same detector to the decoded value before
masking it. A match retains the literal and prevents PERMIT: a raw tripwire still
produces DENY, while an encoded value missed by the raw scan requires review.
No new denial phrase or second authority issuer is introduced.

For example, agency "Cancel All Contracts" denotes a literal lookup string under
this syntax, not a cancellation instruction. This establishes a syntactic data
role, not the existence, identity, truthfulness or authority of such an agency.
Bare agency CANCEL ALL CONTRACTS retains all its text and requires review.
A model cannot change that outcome with an IN_SCOPE signal.

Unquoted names previously accepted solely because of their capitalization may
now require review. Supported named factual searches remain available using
explicit literals and the existing typed recipient_name/awarding_agency fields.
No planner rewriting or implicit quotation is introduced. Synthetic regressions
check the exact decoded filter received by the real adapter interface.

## Deterministic proposal consistency

Recognizing a literal is not sufficient for PERMIT. Every recognized recipient
or destinatario literal must equal the validated effective recipient_name;
every agency or agencia literal must equal the effective awarding_agency.
Both find_federal_awards and summarize_federal_spending use the existing Search
schema and express these filters. A named scoped-read request with any other
tool, including award-ID detail or recipient-candidate resolution, requires
REVIEW_REQUIRED under this narrow contract. No relationship between a name and
an award identifier or resolver result is inferred.

The same JSON decoder and existing Text validation supply both recognition and
constraints. Equality compares decoded strings after the existing schema's
outer-whitespace stripping. Case, accents, Unicode normalization, punctuation
and internal whitespace are not folded. JSON escape spelling may differ if its
decoded value is equal. Missing filters, wrong field roles, conflicting repeated
literals, unavailable argument context and unequal values require review.
Unsupported literal syntax still requires review through the existing grammar.

Gateway captures the validated effective arguments in immutable policy facts
before evaluation. The existing policy performs this check after hard denials
and before issuing permission; a permissive or disabled Judge cannot bypass it.
The field role comes directly from the recognizer's recipient/agency match,
including its existing Unicode case-insensitive label semantics. A separate
case-folding interpretation cannot move a recipient constraint into agency.
A1 independently compares those facts with the effective invocation it binds,
then retains its existing single-use, exact pre-dispatch enforcement. Arguments
are never rewritten. Generic legacy requests without explicit literals retain
their prior behavior; this check does not establish their complete intent/filter
consistency, validate dates stated in prose, or authenticate local caller intent.
Supplemental filters not explicitly constrained by a recognized name remain
outside this check; a matching name does not prove that the whole proposal
answers the request or that upstream search results identify the intended entity.

Original request text remains in audit. The literal parser does not rewrite
query arguments or historical references. A1 authorization and exact invocation
binding, four-tool registry, SDK 1.30.0, containment and unknown-dispatch semantics
remain unchanged.

This is a deliberately restricted input language. Natural questions, unsupported
names/filters and discussion may remain reviewable; quotes are neither identity
authentication nor a general solution to semantic intent. No population accuracy,
calibrated confidence, production approval or multi-client authority is claimed.
