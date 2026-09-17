# External and local sources

Reviewed September 17, 2026.

- [GSA hackathon](https://www.gsa.gov/artificial-intelligence/ai-community-of-practice/events-and-training/mcp-server-and-ai-agent-government-hackathon): project scope, judging and deliverables. Design alignment is not approval.
- [USAspending award search contract](https://github.com/fedspendingtransparency/usaspending-api/blob/master/usaspending_api/api_contracts/contracts/v2/search/spending_by_award.md): filters, fields and pagination.
- [USAspending award detail contract](https://github.com/fedspendingtransparency/usaspending-api/blob/master/usaspending_api/api_contracts/contracts/v2/awards/award_id.md): identifiers and detail fields.
- [USAspending recipient contract](https://github.com/fedspendingtransparency/usaspending-api/blob/master/usaspending_api/api_contracts/contracts/v2/recipient.md): keyword candidate listing. The deprecated `/recipient/duns/` route is not used.
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk): version boundary and maintained 1.x FastMCP API. Installed version is recorded in the environment evidence.
- PRAETOR paths and observed reference commit are listed in PRAETOR_MECHANISM_TRANSFER.md. No local historical metrics are imported as validation.

Live responses have timestamped provenance in artifacts/live-smoke.json. Public records are observations from the listed API, not endorsed findings about a recipient.
