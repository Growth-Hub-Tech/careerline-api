# The adaptive test engine (Day 9)

Code: `app/services/adaptive_engine.py` (scoring and the next level), `app/services/question_picking.py` (which question). Plain arithmetic, no database, fully unit-tested (`tests/test_adaptive_engine.py`, `tests/test_question_picking.py`). Day 10 puts it behind the API.

## How a test runs

1. 16 questions. The first is at JUNIOR.
2. A right answer makes the next question one level harder, a wrong answer one level easier (never above ADVANCED or below BEGINNER).
3. The question at that level is picked the same way as before: the subskill used least so far in this test, then the question this person has seen least in earlier tests, never one already served in this test. If a level runs out, the nearest level is used. Only ACTIVE questions (Day 8) are in the pool.

## How it is scored (no pass or fail)

- **Ability** is a number from 0 to 4: 0-1 BEGINNER, 1-2 JUNIOR, 2-3 MID, 3-4 ADVANCED. A question's difficulty is its level's lower edge (BEGINNER 0, JUNIOR 1, MID 2, ADVANCED 3).
- The chance of a right answer: `0.25 + 0.75 / (1 + e^(-1.7 x (ability - difficulty)))`. 0.25 is the chance of guessing 1 of 4 options. Someone in the middle of a level gets about 78% of that level's questions right and about 48% of the next level's.
- Every ability from 0 to 4 starts equally likely. Each answer multiplies in its chance (a right answer on a hard question pushes the estimate up more than on an easy one). The estimate is the average of what is left.
- **score** (0-100): the ability placed in the level's score band from `seeds/level_thresholds.json` (BEGINNER 0-40, JUNIOR 41-60, MID 61-80, ADVANCED 81-100). **level**: the band of the score.
- **confidence** (0-1): how much of the estimate falls inside that level. Low under 0.6, medium 0.6-0.8, high from 0.8.
- **strengths / weaknesses**: for each subskill with at least 2 answers, the share answered right minus the share expected at the person's ability. 0.2 or more above means strong, 0.2 or more below means weak, otherwise developing. Comparing with the expectation matters in an adaptive test: everyone ends up getting about half right, because the questions follow their level.

## Proof: the simulation

`python scripts/simulate_adaptive.py` runs 1,000 simulated people per level through the real engine and picking, on a bank shaped like ours (5 subskills, 25 questions per level). Each person's true ability is spread evenly inside their level. Each question's true difficulty is its label plus noise (0.3 of a level), because labels are never exact. Output of `python scripts/simulate_adaptive.py --people 1000 --seed 1`:

```
Adaptive test simulation: people per level: 1000, label noise 0.3 of a level, 16 questions each

true level   mean    sd   p10   p50   p90  exact confidence
BEGINNER     28.3  13.9    11    25    47  76.1%       0.78
JUNIOR       49.5  12.3    34    49    65  64.5%       0.62
MID          70.4  10.8    56    70    85  62.6%       0.65
ADVANCED     87.8   7.2    77    91    95  85.4%       0.84

Confusion (rows: true level, columns: level given, % of the row):
            BEGINNER    JUNIOR       MID  ADVANCED
BEGINNER       76.1%     22.7%      1.2%      0.0%
JUNIOR         18.0%     64.5%     17.1%      0.4%
MID             0.0%     17.8%     62.6%     19.6%
ADVANCED        0.0%      0.1%     14.5%     85.4%

Exact level: 72.2%   within one level: 99.6%
Separation of neighbouring levels (d; above 1 is well apart): BEGINNER-JUNIOR 1.62, JUNIOR-MID 1.81, MID-ADVANCED 1.90
Average confidence when the level is right: 0.75, when wrong: 0.64

With more or less noise in the difficulty labels:
  noise 0.0: exact 70.1%, within one 99.2%, d 1.63, 1.59, 1.86
  noise 0.6: exact 67.0%, within one 99.0%, d 1.53, 1.62, 1.64

Pure guessing: average score 5.6, 100% get BEGINNER
Always picking the longest option (Frontend Web Development, its ACTIVE questions): average score 48.8; levels BEGINNER 45%, JUNIOR 10%, MID 17%, ADVANCED 29%
```

What it shows:

- **The levels separate.** The average score rises level by level (28, 50, 70, 88). Neighbouring levels are 1.6 to 1.9 standard deviations apart. 72% get exactly their true level and 99.6% are within one level. Almost all the misses are people whose true ability is near the edge of a level.
- **Confidence is honest.** It is higher when the level is right (0.75) than when it is wrong (0.64), so a "low" confidence is worth showing.
- **Robust to imperfect labels.** With twice the label noise, 67% are still exact and 99% within one level.
- **Guessing gets BEGINNER.**
- **Risk: the length give-away.** Someone who always picks the longest option, on the questions of Frontend Web Development that are ACTIVE today, averages 49 and reaches ADVANCED 29% of the time. The questions with a mild length give-away (1.3x to 2.0x) are still served. Fixing their wrong options (docs/question-quality.md) is what closes this.

The question difficulties are the authors' labels. Once real answers come in, measure each question's difficulty from them and use it in place of the label (`difficulty()` in the engine is the one place to change).
