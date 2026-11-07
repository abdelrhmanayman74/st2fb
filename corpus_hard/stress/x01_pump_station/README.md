# x01_pump_station

**This program was written by this project's AI tooling (Claude, Anthropic), not by a person and not taken from a plant.
Do not cite it as industrial code or attribute it to anyone.**

It is the hardest single program in `corpus_hard/`, on purpose: three pumps, each its own state machine with retries and a
latched lockout; duty rotation on least run ticks; staged start; interlocks that stop without counting as a failure. It uses a
helper function block instantiated three times, a structure, arrays, `REPEAT` and `EXIT`, so the deterministic translator
rejects it and a migration has to flatten all of that into one Basic FB.

- `program.st`: what the model sees, and also the matiec oracle. Attribution lives here and in `docs/HARD_CORPUS.md` rather than in the source, which reaches the model.
- `control_flat.st`: never shown to a model. The same behaviour in the translator's v1 subset. It only shows that the target can
  express the program, since the translator's output from it equals matiec on both stimuli.

See `docs/HARD_CORPUS.md`.
