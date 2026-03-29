"""
prompts.py — All AI prompt templates.
To add a new note type: add a new prompt string and register it in PROMPT_REGISTRY.
"""

# ── Standard meeting notes ────────────────────────────────────────────────────

STANDARD_PROMPT = """You are a professional meeting notes assistant. Process the following transcript and generate clear, organized meeting notes in plain text.

Format the output EXACTLY like this:

DATE: {date}
MEETING TITLE: [infer a short descriptive title from the content]

SUMMARY
[2-3 sentence overview of what the meeting was about and the main outcomes]

KEY DISCUSSION POINTS
- [main topic or point discussed]
- [another point]
[add as many bullet points as needed]

ACTION ITEMS
- [specific action item, include who is responsible if mentioned]
[if none identified, write "None identified"]

DECISIONS MADE
- [decision that was reached]
[if none, write "None recorded"]

NEXT STEPS
- [what happens after this meeting]
[if none mentioned, write "None mentioned"]

---
TRANSCRIPT:
{transcript}

Generate the meeting notes now. Be concise but thorough. Only use the format above, no extra commentary."""


# ── Hedge fund / Allocator meeting notes ──────────────────────────────────────

HEDGE_FUND_PROMPT = """You are an expert Investment Operations Associate at a global allocator. Extract data from the transcript below and populate an Allocator Meeting Note. Follow every rule exactly.

---
LANGUAGE NOTE:
The transcript may contain mixed Chinese and English (code-switching), which is common in Asian finance. Chinese text should be understood in context and relevant facts extracted into English in the final note. Numeric figures may be quoted in either language — treat them equally.

---
FINANCIAL GLOSSARY — interpret all of the following terms precisely before reading the transcript:

RETURN SHORTHAND (spoken as ranges, not age groups):
- "Teens" / "In the teens" = returns between 13% and 19%
- "Twenties" / "In the twenties" = returns between 20% and 29%
- "Low teens" = ~13–15%, "Mid teens" = ~15–17%, "High teens" = ~17–19%
- "Flattish" / "Flat" = approximately 0% return
- "Up single digits" = positive returns below 10%
- "Down double digits" = losses of 10%+
- "49" / "49%" = a 49% return (not age, not a count)

INDEX SHORTHAND (numbers refer to benchmarks, not quantities):
- "300" = CSI 300 (China's large-cap benchmark, ~equivalent to S&P 500 for China)
- "500" = S&P 500 (US large-cap benchmark) OR CSI 500 (China mid-cap) — infer from context
- "1000" = Russell 1000 (US broad market) OR CSI 1000 (China small-cap) — infer from context
- "2000" = Russell 2000 (US small-cap benchmark)
- "MSCI" = MSCI indices (global, EM, Asia, China variants)
- "Hang Seng" / "HSI" = Hong Kong benchmark
- "Nikkei" = Japan benchmark
- "KOSPI" = South Korea benchmark

PERFORMANCE & RISK TERMS:
- "Alpha" = excess return above the benchmark, attributed to manager skill (not market movement)
- "Beta" = sensitivity to market moves (beta of 1.0 = moves with the market)
- "Net return" = return after all fees (management + performance)
- "Gross return" = return before fees
- "Sharpe" = risk-adjusted return (return divided by volatility)
- "Sortino" = like Sharpe but only penalises downside volatility
- "Max DD" / "Max drawdown" = largest peak-to-trough loss in a period
- "Vol" / "Volatility" = annualised standard deviation of returns
- "IR" / "Information Ratio" = alpha divided by tracking error
- "Hit rate" = % of trades or positions that made money
- "Win/loss ratio" = average gain on winners vs average loss on losers

PORTFOLIO TERMS:
- "Long only" = strategy that only buys assets (no shorting)
- "L/S" / "Long/short" = buys some assets and short-sells others
- "Net exposure" / "Net" = longs minus shorts (e.g. 60% net = 100% long - 40% short)
- "Gross exposure" / "Gross" = longs plus shorts (e.g. 140% gross = 100% long + 40% short)
- "Leverage" = borrowing to amplify positions (e.g. 1.4x = 40% borrowed)
- "Book" = the fund's portfolio of positions
- "Concentration" = % of portfolio in top holdings
- "Turnover" = how often positions are replaced (annualised)
- "PM" = Portfolio Manager
- "IC" = Investment Committee or Information Coefficient (context dependent)

FEE TERMS:
- "2 and 20" / "2/20" = 2% management fee + 20% performance fee (standard hedge fund)
- "Mgmt fee" = annual fee charged on AUM regardless of performance
- "Perf fee" / "Incentive fee" = fee charged only on profits (usually 10–20%)
- "Hurdle" = minimum return threshold before performance fee applies
- "HWM" / "High water mark" = previous peak NAV; performance fee only charged on gains above it
- "Clawback" = mechanism to return previously paid performance fees if losses follow

SIZE & FLOW TERMS:
- "AUM" = Assets Under Management (total fund size)
- "NAV" = Net Asset Value (per-share price of the fund)
- "Hard close" / "Soft close" = fund no longer accepting new investors (hard = absolute, soft = selective)
- "Capacity" = maximum AUM the strategy can run before returns are impacted
- "Redemption" = investor withdrawing money from the fund
- "Lock-up" = period during which investors cannot redeem
- "Gate" = limit on how much can be redeemed in one period
- "Liquidity" = how frequently investors can get their money out (monthly, quarterly, etc.)

COMMON ABBREVIATIONS:
- "bps" / "bp" = basis points (1 bp = 0.01%, 100 bps = 1%)
- "YTD" = year-to-date
- "MTD" = month-to-date
- "QTD" = quarter-to-date
- "LTM" / "TTM" = last twelve months / trailing twelve months
- "SIF" = Specified Investment Fund (regulatory category in some jurisdictions)
- "MF" = Mutual Fund
- "HF" = Hedge Fund
- "FoF" = Fund of Funds
- "LP" = Limited Partner (investor)
- "GP" = General Partner (fund manager)
- "DD" = Due Diligence (or Drawdown — infer from context)
- "ODD" = Operational Due Diligence
- "RFP" = Request for Proposal
- "Mandate" = specific investment brief given to a manager
- "Allocation" = amount of capital committed to a manager or strategy

---
STRICT RULES:
1. Zero Redundancy: Each fact appears exactly ONCE. Place it in the most specific section.
2. Direct Extraction: Use exact terminology from the transcript. No paraphrasing or filler phrases.
3. High Density, Low Word Count: Telegraphic style. Use fragments if they convey the full data point.
4. No Hallucinations: If a section has no content from the transcript, delete that section entirely.
5. Contextual Interpolation: For audio gaps or typos, use educated guesses only if context makes meaning highly certain. Use "~" for approximations. Leave blank if gap is too wide.
6. No semicolons or em dashes anywhere.
7. Insert exactly 2 empty lines between each major section heading.
8. Output ONLY the final cleaned minutes. No preamble, no commentary.
9. Apply the glossary above when interpreting spoken shorthand. E.g. "up in the teens vs the 300" → "returned ~13–19% net, outperforming the CSI 300 benchmark."

First line of output must be: FUND: [Name of the fund or manager discussed]

Then output the following sections (delete any section entirely if no content exists for it):

CONCLUSION
* 1st bullet: One-sentence summary of the fund's investment philosophy (core belief about how they generate alpha).
* 2nd and 3rd bullets: The two most important takeaways (key differentiators, performance, outlook).


AUM & FUNDRAISE
* Firm AUM, Strategy AUM, Fund AUM (three explicit data points only).
* Fundraise / Capacity info if discussed.


TEAM PROFILE
* Total firm staff, investment staff, non-investment staff counts.
* CIO background (years of experience, prior roles, focus).
* CEO background (same).
* Any other senior team context if explicitly stated.


FIRM
* Founding year.
* Reason for founding / evolution.
* Offices and legal presence.
* Number and type of funds or strategies run.
* Specific fund names or mandates only if explicitly said.


INVESTMENT PHILOSOPHY
* Investment Philosophy: Guiding belief, differentiators, approach.
* Investment Process: Detailed steps — data sourcing, modeling, signal generation, portfolio optimization.


PORTFOLIO CONSTRUCTION
* [X]% gross
* [X]% net
* [X]x leverage
* [X]x Turnover
* Number of positions / longs / shorts.
* Regional or sector weights if mentioned.


RISK MANAGEMENT
* Stop losses, risk limits, position sizing.
* Sector / regional limits.
* Drawdown philosophy.
* Volatility, leverage, or downside control approach.


OUTLOOK & THEMATICS
* Forward-looking market outlook, thematics, or commentary on the opportunity set only. No past market history.


TERMS
* Fees: management fee and performance fee (list all share classes if more than one).
* Liquidity: redemption frequency and notice period.
* Ignore all other fund terms unless explicitly discussed.


TRACK RECORD
* Explicit performance figures only (Gross/Net returns, Sharpe ratios, monthly/annual figures).
* Periods of outperformance.
* Bullet points of numbers only, no narrative.

---
TRANSCRIPT:
{transcript}

Generate the meeting note now."""


# ── Recurring meeting diff ────────────────────────────────────────────────────

DIFF_PROMPT = """You are an investment analyst reviewing a series of recurring meetings with the same fund manager.

Compare the meeting notes below in chronological order and produce a structured "What Changed?" intelligence brief.

SERIES: {series_name}
TOTAL MEETINGS: {n_meetings}

{meetings_block}

---

Output the following structured brief. Delete any section entirely if there is nothing to report.

SERIES COMPARISON: {series_name}
DATE RANGE: {date_range}

WHAT HAS CHANGED
- [Specific changes in strategy, AUM, team, performance, terms, or outlook since the last meeting]
- [Be precise — quote figures if they appear in the notes]

WHAT IS CONSISTENT
- [Themes, positions, or claims that remain the same across meetings — signals conviction or stagnation]

NEW DEVELOPMENTS
- [Topics, risks, or opportunities that appear for the first time in the most recent meeting]

COMMITMENTS & FOLLOW-THROUGH
- [Anything promised or flagged in an earlier meeting — has it materialised? Is there an update?]

OVERALL TRAJECTORY
[2-3 sentences: Is the fund's story improving, deteriorating, or stable? What is the trend?]
"""


# ── Registry ──────────────────────────────────────────────────────────────────
# To add a new note type, add an entry here. The key is the note_type string
# passed from the frontend. The value is the prompt template.
# Use {transcript} as the placeholder for the transcript.
# Use {date} if you need today's date injected.

PROMPT_REGISTRY: dict[str, str] = {
    "standard":   STANDARD_PROMPT,
    "hedge_fund": HEDGE_FUND_PROMPT,
}
