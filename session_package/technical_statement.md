# Sales-O-Matic

Note this is a hand-written document. 


## Executive Summary (Business Benefit description)

Sales-O-Matic allows a technical or commercial salesperson to offload initial Customer profile and persona research to a dedicated research agent. A typical use-case would be a preparation for initial meeting or demand generation representative's initial research for email/phone/LinkedIn outreach.

Sales-O-Matic relies on Tavily APIs to retrieve relevant and fresh information in order to "ground" agent response and tie it to actual data sources (official web-sites, earnings reports, news). Response is structured in a way which allows user to immediately get a grasp on the main components: company overview, recent news and events related to the company, strategic programs and priorities, personas and suggested talking points given users role and company (assumption for initial demo is that user is a salesperson  (b2b sales) in a tech company).

Each retrieved item is accompanied by a source (called citation), allowing user to dive deeper into specific topic.
Solution uses a thin (local) MCP server, allowing user or user's IT Team to easily embedd agent into existing AI Tooling set used in company's environment (Claude for Work, OpenAI Codex, Microsoft Copilot or any of the AI-enabled IDEs).

Overall Sales-O-Matic provides a cost-efficient (at a fraction of a comparable SaaS solution cost) way to drastically reduce initial research time on a target Customer in a pre-sales process, freeing up time for account executives and demand generation representatives and allowing them to concentrate on more impactful actions, such as actually performing a customized and tailored outreach based on the agent search results.


## Solution Description

Sales-O-Matic (https://github.com/omni1504/tavily-lab) is a Python application consisting of the following 3 main parts:
- Main program (starter_agent.py), incorporating CLI- and STDIO-based output schemes for Tavily-based agentic search
- Local Evaluation Harness (/evals)
- Thin MCP server layer (/mcp_server) to serve starter_agent.py as a tool for upstream GenAI applications (e.g. Claude for Work/Code)

### Main program (starter_agent.py)

#### Structure
Consists of:
- Langchain-based agent which uses Amazon Bedrock-based Claude Sonnet 4.6 model (refer to build_agent function)
- Main function which implements Langchain streaming system to support CLI-based Q&A mode for Sales-O-Matic ;
- generate_brief (entrance) function used by MCP server for Sales-O-Matic invocation;
- set of supporting and tooling functions (CLI chat formatters for output and citations; CLI arguments parsers; loggers;)

LangChain tracing (to LangSmith Cloud) is instrumented in the code (built-in) and is enabled by CLI parameter (e.g. for testing eval runs)
Main program has CLI params to be invoked for producing brief to the compaby (--brief).


#### Search 
Langchain agent receives a system prompt to generate a brief using Tavily search results and gets Tavily search tool as part of the parameter set during agent client creation. Prompt has strong rules for grounding responses with citations provided by Tavily. Static code looks through all URLs provided by Tavily and indicates to the user which parts of responses are coming from grounded search (Tavily)

In order to control Tavily search scope and breadth, LangChain's ToolCallLimitMiddleware (https://reference.langchain.com/python/langchain/agents/middleware/tool_call_limit/ToolCallLimitMiddleware) parameter is used to limit the number of searches agent performs using Tavily API. 

Code also grounds (forces to filter) news search responses by configurable "freshness" interval (90 days by default) to ensure search returns relevant data.

Agent's prompt is forcing (rather requesting) model to perform Tavily search per section (Overview, Recent news, Main personas, etc) and ToolCallLimitMiddleware controls how many iterations are possible (default is 10)

Agent search in two rounds - the first step will send 4 Tavily searches per section (all but news will be General Search, news will be filteres by topic = "news' and bound by start date - not older than 90 days). If a section has fewer than 2 relevant results, agent will run up to 2 refined searches in it - if no restuls, agent will put a comment saying there is insufficient data.

#### Thought process
Keep core program small, decouple evals, MCPs. For Tavily search, decision has been made to run separate searches per section (see below) in an attempt to get more relevant (to the section) search results. In order to control possible API invocation costs, limit on searches per agent request has been implemented -> idea was to add evaluation harness and then experiment with additional search settings or let Tavily go deeper (evaluation harness was implemented but additional experimentation is still pending due to lack of time). 
Initial results revealed disreptancy between retrieved search results and what agent was sending back to the user which was somewhat fixed by prompt hardening (to ground results to search results and attach citations), but may need more work.

Langsmith tracing has been used from the very first run to (manually) confirm initial agent response quality, call duration and (indirectly) cost implications. Original idea was to build eval harness into Langsmith tracing, but decision has been to use local for now in order to get immediate visibility and "quick win" with a feature request opened in the repo to integrate  eval harness with observability platform.

AWS Bedrock is used for model invocation (as author is more familar with this infra).


### Local Eval Harness (/evals)

Consists of several components:
- Main entry point: run_evals.py is run by user in two modes (sequentially):
  - **collect** invoked main program (starter_agent.py) in "record mode" ('`starter_agent.py --brief --no-tracing --record`, results dropped in JSON, this included agent response, Tavily search results, source URLs) against 5 companies which author selected as a golden set and manually defined grounded data (see golden_set.toml). 
  - **score** It invokes scoring.py which runs deterministic against saved records (so can be re-run at lower cost if scoring methodology changes). Deterministic will check response structure, citation coverage, URL provenance, news window (dates), query hygiene, no-citation rate (we want it to be smaller). Then score mode invokes LLM judge (judge.py) to provide a per-brief quality scores. 
  - LLM judge will use Amazon Bedrock-based model (with thinking mode off) with a prompt which requests to check the following from the reports:
```
- Q1 reference_facts: agreement with the reference facts given (contradictions score 1-2).
- Q2 overview_completeness: business, industry, size, headquarters, products are covered.
- Q3 personas_relevance: real, current, decision-relevant people; business and technical roles.
- Q4 talking_points_grounding: every talking point traces to facts stated in the brief.
- Q5 usefulness: actionable separately for Sales and for Technical Presales.
```
  - In addition, LLM judge will compare reports statement (=claim) with source text provided by Tavily to confirm accurate information being provided by a model used by an agent.
- Final scoring is a set of gates per company. Gates percentages still require some tuning, as initial experimentation has showed that gate score for matching citation text with actual text is too strict. 
- All results and intermediate files (e.g. reports) are saved into /evals/results folder, per run

### MCP Server (/mcp_server)

Standard FastMCP endpoint running locally (via stdio) with a prompt forcing calling model to ensure citations are passed over and honered in the output.


## Solution Approach

Solution has been developed using Claude Code (Opus 5.5 mode) via PLan - Implement - Test - PR routine (plans are attached). For each feature human has been asking to create a plan, iterating on it and then analyzing the code at PR review stage.

During initial testing and plan ideation a number of enhancements and defects has been identified, which are tracked as issues in the repository - some of them are also mentioned in the Roadmap section of the readme. Immediate defects have been fixed - some of the enhancement are left out of the initial release.

### Misc - Claude Session Log Parser

/parser folder contains a vibe-coded Claude Session log parser which provided a [more] human readable Claude Session log for human review


## Reference Files (LLM-generated text below)

The `session_package/` folder holds the artifacts of the Claude Code session that built Sales-O-Matic (2026-11-13). 

- `README.md`: an index of the package and the ID of the session it came from.
- `technical_statement.md`: this solution brief (hand-written except for this specific section).
- `agent/`
  - `CLAUDE.md`: the project guide that steers the coding agent (stack, commands, configuration, workflow and rules), with the AWS profile name redacted.
- `skills/`
  - `feature-workflow/SKILL.md`: the mandatory per-feature workflow (plan → user approval → branch → small tested steps → PR via `gh`), created during the session.
  - `code-hygiene/SKILL.md`: the linting, formatting, typing and testing rules the agent follows before declaring any task done, provided at session start.
- `plans/history/`: each full plan the agent wrote before a feature, recovered from the session log:
  - `01-feature-1-…`: first plan for LangSmith tracing (CLI flags that override `.env`, project `tavily-research-agent`).
  - `02-feature-1-…`: revised tracing plan, with `.env` as the only source of settings and a startup log line.
  - `03-feature-2-…`: first plan for the `--brief` account-research mode (sections, citations, 90-day news window).
  - `04-feature-2-…`: revised `--brief` plan with the exact code changes, the search cap via `ToolCallLimitMiddleware`, the sources appendix and tests.
  - `05-feature-3-…`: plan for the local eval framework (golden set, deterministic checks, LLM judge).
  - `06-feature-4-…`: plan for the local stdio MCP server exposing `get_brief`.
- `samples/`
  - `session.jsonl`: the raw Claude Code session log (about 5.4 MB).
  - `session.md`: the same log rendered as readable Markdown by `parser/parse_session.py`.
The plans are pre-implementation snapshots, so some details changed later. 






