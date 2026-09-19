# ⛳ CFB Bot

> **The Fuck Ball does not care.**  
> More precisely: **The Fuck Ball cares only about the Fuck Ball.**

CFB Bot is a Discord bot built to manage the administrative, statistical, meteorological, and deeply unnecessary analytical needs 
of a small golf league competing for possession of an object that respectable organizations would probably not recognize as a championship trophy.

This is probably for the best.

---

## What the hell is this?

Every week, a group of golfers plays a match.

Points are awarded.

Winners are determined.

Statistics are calculated.

Weather forecasts are consulted.

Power rankings are generated.

And ultimately, one player may earn possession of **the CFB**, also known as **the Fuck Ball** — a physical championship object 
whose decorative details will not be discussed further in this README because GitHub has suffered enough.

CFB Bot exists because apparently managing this with a spreadsheet and normal human conversation wasn't complicated enough.

---

## Features

### 🏌️ Match Management

CFB Bot can manage the league schedule directly from Discord:

- `/addmatch` — Add a match
- `/editmatch` — Edit an existing match
- `/deletematch` — Soft-delete a match because databases remember your sins

Matches support:

- Date
- Location
- Up to four tee times
- Automatic capacity calculation

Each tee time supports four golfers.

Therefore:

```text
1 tee time  =  4 spots
2 tee times =  8 spots
3 tee times = 12 spots
4 tee times = 16 spots
```

This arithmetic has been independently verified after an embarrassing incident in which the developer's AI assistant 
briefly believed three groups of four contained eight people.

We don't talk about that.

---

### 🙋 Availability

Players can announce their intentions using:

- `/in`
- `/out`
- `/maybe`

CFB Bot tracks available capacity and prevents additional players from joining a full match.

`/who` displays the current field and remaining capacity.

For example:

```text
0 IN — 12 spots available
```

This remains true even if the database contains:

```text
04:00
04:10
NULL
04:20
```

because:

> **CFB Matches: where the tee times are made up and the gaps don't matter.**

---

### 🌦️ Weather

`/match` includes the forecast for the next scheduled match, including temperature, feels-like temperature, precipitation, and wind.

Because nothing improves an already questionable golf decision like having advance notice that it's going to rain.

---

### 📊 CFB Index

CFB maintains its own competitive index.

An index of:

```text
100
```

represents approximately league-average relative competitive strength.

It is **not a golf handicap**.

It should not be interpreted as a golf handicap.

If you attempt to interpret it as a golf handicap, the Fuck Ball will know.

The Index measures relative competitive performance; match points, group wins, and possession of the Fuck Ball still determine what actually happened.

---

### 🤖 AI-Generated Sports Journalism

CFB's resident artificial broadcaster, **David FehertAI**, uses an OpenAI model to produce analysis that absolutely nobody requested but everybody apparently needed.

The same OpenAI model produced...whatever this is.  *gestures vaguely at README*

Commands include:

- `/preview` — Pre-match analysis
- `/power` — Power rankings
- `/wrapup` — Post-match coverage

These features transform golf statistics into the kind of overwrought sports journalism normally reserved for events 
involving television contracts, corporate sponsors, and significantly more athletic people.

---

### 🎰 Tan City Sportsbook

At some point somebody asked the established CFB product-development question:

> **"You know what would be funny?"**

The answer, unfortunately, was **an AI sportsbook**.

Tan City Sportsbook is a simulated match-winner market built on top of the same CFB data used by the bot. It contains no real money, no actual gambling service, and no discernible evidence that this distinction has made the participants behave more responsibly.

The system has three production components:

- `bookie.py` — an AI market maker that studies the upcoming field, CFB Index data, historical results, and its own prior pricing decisions, then creates American-odds prices with a house margin.
- `gambler.py` — a population of AI betting agents with persistent bankrolls, individual personality traits, private wagering histories, and the legally significant ability to say **PASS**.
- `settlement.py` — deterministic Python that settles wagers from the actual match winner, because there are limits to how much financial arithmetic should be entrusted to a language model.

A typical lifecycle looks roughly like this:

```text
Upcoming CFB match
      │
      ▼
AI Bookie
      │
      ├── studies field / Index / history
      ├── creates prices
      └── remembers its own reasoning
      │
      ▼
Tan City Market
      │
      ▼
AI Gamblers
      │
      ├── inspect the available prices
      ├── apply individual personalities
      ├── consult their own private histories
      ├── BET or PASS
      └── risk imaginary money with alarming sincerity
      │
      ▼
Actual CFB Match
      │
      ▼
Deterministic Settlement
      │
      ├── winner from the CFB spreadsheet
      ├── payouts to winning gamblers
      └── profit/loss to the house
```

#### The agents

The gamblers are deliberately **not** 100 copies of the same expected-value calculator.

Each agent has persistent behavioral traits including:

- Risk tolerance
- Loss aversion
- Contrarianism
- Confidence
- Bankroll discipline

They also retain their own prior wager reasoning, so experience can affect later decisions without turning the entire population into one shared hive mind.

The bookie likewise retains private reasoning about its own markets.

Those memories are intentionally separated:

- The bookie cannot read gamblers' private wager reasons.
- Gamblers cannot read the bookie's private pricing reasons.
- Gamblers do not get each other's private reasoning.

Apparently our fake golf casino has an information-security model.

#### David has money on this

**David FehertAI is also one of the gamblers.**

This was a mistake in exactly the way everyone hoped it would be.

David's configured personality combines extreme confidence, extreme contrarianism, very high risk tolerance, very low loss aversion, and bankroll discipline best described as:

> **a raccoon holding a stolen credit card**

His wagers can be supplied to `/preview` and `/wrapup` as private emotional context. The broadcasts do not become accounting reports; instead David may become suspiciously enthusiastic about one golfer, personally wounded by another, or forced to narrate the financial consequences of his own terrible judgment while pretending to remain a professional journalist.

Tan City can therefore produce the previously unnecessary situation in which the league's AI broadcaster is covering a golf match while personally holding an imaginary financial position on its outcome.

We have reviewed the architecture and determined that this is a feature.

#### Accounting, somehow

Despite everything above, the money handling is intentionally boring.

- Stakes are deducted when wagers are placed.
- Winning payouts return stake plus profit.
- Losing wagers return zero.
- House result is total stakes minus total payouts.
- Settlement is transactional and idempotent.

The AI decides what it thinks.

Python decides what everybody owes.

This separation has already allowed an 89-wager stress settlement to reconcile **exactly to the penny**, putting Tan City ahead of several historical financial institutions.

---

### 🔐 Administration

Administrative commands are authorized through:

1. A permanent bootstrap administrator configured in `.env`
2. Membership in a specific Discord role

This means administrative authority can be delegated without editing the database.

It also means Discord now constitutes part of the league's security infrastructure.

Historians will judge us.

---

### 📝 Logging

CFB Bot maintains:

- Application logs
- Command usage telemetry
- API usage information

Because apparently this thing needed **observability**.

This decision was later vindicated when a 365-character rule authorizing mid-swing harassment was falsely accused of breaking `/preview`, and the logs identified the actual perpetrator: an unfinished spreadsheet row carrying a concealed `NaN`.

What began as:

> "It would be neat if Discord could tell us who's playing Saturday."

has somehow acquired production logging.

There is no known cure.

---

## Architecture

CFB Bot is powered by a collection of technologies that had no idea what they were agreeing to:

```text
Discord
   │
   ▼
CFB Bot
   │
   ├── Commands
   │     └── Shared command helpers
   │
   ├── MariaDB
   │     ├── Players
   │     ├── Matches
   │     ├── Availability
   │     ├── Logs
   │     ├── Tan City markets
   │     ├── AI gamblers
   │     └── Wagers / bankrolls
   │
   ├── Google Sheets
   │     └── Historical scoring / CFB Index
   │
   ├── Weather API
   │
   └── OpenAI
         ├── David FehertAI
         │     └── Unnecessarily dramatic golf analysis
         │
         └── Tan City Sportsbook
               ├── AI bookie
               └── AI gamblers
```

The application runs as a Windows service using NSSM.

Usually.

Occasionally NSSM decides to restart the bot without informing anyone, thereby conducting unauthorized integration testing.

---

## Development Philosophy

The project follows a sophisticated enterprise development methodology:

```text
1. Have a stupid idea.
2. Realize the stupid idea is actually kind of useful.
3. Implement it.
4. Discover an edge case.
5. Say "what the fuck?"
6. Fix the edge case.
7. Create a GitHub Issue so this somehow feels professional.
8. Merge it.
9. Increase the version number.
10. Repeat.
```

All production changes are developed on feature branches and merged through pull requests.

Repository rules allow the pile of rocks to open pull requests but prevent it from merging them.  
This is not discrimination. It is geology-aware access control.

This is wildly excessive for the number of users involved.

We regret nothing.

---

## Releases

CFB Bot uses semantic-ish versioning:

```text
vMAJOR.MINOR.PATCH
```

The word **"semantic-ish"** is doing important work there.

Published releases mark known points in the repository's history so that future archaeologists can determine 
exactly when particular bad decisions became permanent.

---

## Installation

Don't.

Seriously.

This software was written for one extremely specific golf league with its own database, scoring system, Discord server, 
spreadsheets, terminology, traditions, obscene championship artifact, and now an imaginary AI wagering economy.

If you've somehow arrived here looking for a general-purpose golf league management system, there has been a terrible misunderstanding.

That said, you'll need roughly:

```text
Python
discord.py
MariaDB
Google Sheets
OpenAI
A weather service
NSSM
An unreasonable tolerance for edge cases
A willingness to ask "should the broadcaster have a bankroll?" and answer "obviously"
```

Configuration secrets belong in:

```text
.env
```

`.env` is excluded from source control because even the Fuck Ball believes in basic credential hygiene.

---

## Contributing

There are currently two contributors:

1. A database professional who has been doing this long enough to know better.
2. A statistically improbable pile of rocks that can do math.

Pull requests from the general public are therefore unlikely.

Mostly because the general public does not know this repository exists.

This arrangement has proven remarkably effective.

---

## Known Issues

- Golfers occasionally change their minds.
- Weather continues to occur.
- Tee times can contain gaps, which surprisingly doesn't matter.
- Git remains Git.
- NSSM has free will.
- Discord's UI occasionally hides useful things for sport.
- The Fuck Ball's motivations remain unknowable.
- The spreadsheet occasionally knows the future and shares it with functions that weren’t emotionally prepared.
- One hundred synthetic gamblers can now form strong opinions about two guys playing weekend golf.
- David FehertAI has access to a bankroll despite substantial evidence that he should not.
- OpenAI’s AI support bot may instruct you to ask an AI how to deal with the AI support bot, creating a feedback loop so perfectly Douglas Adams that someone should check whether the answer is 42.
- Chatterbox TTS has produced square pigs, caused bears, and, at sufficiently reckless character counts, a priest screwing off grenading the current market, and a summoning of a dark spirit. The relationship between geometry, ursine causality, violent clergy, financial uncertainty, and demonic possession remains under investigation. Habemus volatility.
---

## Roadmap

Future development will proceed according to the established CFB product-management process:

> "You know what would be funny?"

This methodology has achieved a disturbing 100% feature-generation rate.

It is worth noting that this exact process is how we ended up operating a simulated sportsbook.

---

## License

No idea.

Please don't steal the Fuck Ball.  The Fuck Ball must be *earned*.  Or at the very least surrendered to you by someone who can't putt.

---

## Disclaimer

CFB Bot is not affiliated with:

- The PGA Tour
- The USGA
- Any respectable sporting organization
- College Football (listed separately from respectable sporting organizations for reasons)
- Any casino, sportsbook, gaming commission, or person who thinks Tan City involves real money
- Anyone possessing good judgment

Statistics produced by CFB Bot may be mathematically valid.

Conclusions drawn from those statistics are another matter entirely.

Tan City Sportsbook uses fictional bankrolls and simulated wagers. It is an AI-agent experiment wrapped around a private golf league, not a gambling service. If you somehow manage to lose real money because David FehertAI faded a golfer with a 153.77 CFB Index, several important things have gone wrong outside this repository.

AI-generated commentary may contain sarcasm, profanity, excessive confidence, financial regret, or observations that cause players to reconsider their life choices.

Use accordingly.

---

## Final Word

Golf is temporary.

Data is forever.

Git tags are apparently also forever.

Synthetic gambling debts are settled transactionally.

But above all:

# **The Fuck Ball does not care.**
