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

### 🔐 Administration

Administrative commands are authorized through:

1. A permanent bootstrap administrator configured in `.env`
2. Membership in the Discord `Admins` role

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
   │     └── Logs
   │
   ├── Google Sheets
   │     └── Historical scoring / CFB Index
   │
   ├── Weather API
   │
   └── OpenAI
         └── Unnecessarily dramatic golf analysis
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
spreadsheets, terminology, traditions, and obscene championship artifact.

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

---

## Roadmap

Future development will proceed according to the established CFB product-management process:

> "You know what would be funny?"

This methodology has achieved a disturbing 100% feature-generation rate.

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
- Anyone possessing good judgment

Statistics produced by CFB Bot may be mathematically valid.

Conclusions drawn from those statistics are another matter entirely.

AI-generated commentary may contain sarcasm, profanity, excessive confidence, or observations that cause players to reconsider their life choices.

Use accordingly.

---

## Final Word

Golf is temporary.

Data is forever.

Git tags are apparently also forever.

But above all:

# **The Fuck Ball does not care.**
