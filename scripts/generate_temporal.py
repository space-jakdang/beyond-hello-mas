"""Independent artificial dynamics; not fitted to private data or clinical outcomes."""
import random

MONTHS = [f'2025-{m:02}' for m in range(1,13)]
PATTERNS = ('stable','trend','shock','recovery','missing','noisy')
TEST_SEEDS = (17,29,43)


def generate(seed):
    rng = random.Random(seed)
    rows = []
    for dong in range(47):
        for group in range(8):
            pattern = PATTERNS[(dong*8+group) % len(PATTERNS)]
            base = rng.uniform(.2,.45)
            for m, month in enumerate(MONTHS):
                level = base
                if pattern == 'trend': level += .045*m
                if pattern == 'shock' and m >= 7: level += .4
                if pattern == 'recovery' and m >= 5: level += max(0.,.5-.08*(m-5))
                truth = max(0.,min(1.,level + rng.gauss(0,.02)))
                observed = max(0.,min(1.,truth + rng.gauss(0,.12 if pattern=='noisy' else .025)))
                if pattern=='missing' and rng.random()<.5: observed=None
                rows.append({'cohort':f'synthetic-{dong:02}-{group}','month':month,'value':observed,
                             'truth':truth,'pattern':pattern})
    return rows
