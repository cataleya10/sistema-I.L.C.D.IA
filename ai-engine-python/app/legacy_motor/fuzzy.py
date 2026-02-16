import difflib


def _as_text(value) -> str:
    return str(value or "").upper().strip()


class fuzz:
    @staticmethod
    def ratio(a, b) -> int:
        a_norm = _as_text(a)
        b_norm = _as_text(b)
        if not a_norm and not b_norm:
            return 100
        if not a_norm or not b_norm:
            return 0
        return int(round(difflib.SequenceMatcher(None, a_norm, b_norm).ratio() * 100))

    @staticmethod
    def token_set_ratio(a, b) -> int:
        a_tokens = sorted(set(_as_text(a).split()))
        b_tokens = sorted(set(_as_text(b).split()))
        return fuzz.ratio(" ".join(a_tokens), " ".join(b_tokens))

    @staticmethod
    def partial_ratio(a, b) -> int:
        a_norm = _as_text(a)
        b_norm = _as_text(b)
        if not a_norm or not b_norm:
            return 0
        short, long = (a_norm, b_norm) if len(a_norm) <= len(b_norm) else (b_norm, a_norm)
        if short in long:
            return 100
        if len(short) == len(long):
            return fuzz.ratio(short, long)
        max_score = 0
        window = len(short)
        for i in range(0, len(long) - window + 1):
            segment = long[i:i + window]
            score = fuzz.ratio(short, segment)
            if score > max_score:
                max_score = score
            if max_score == 100:
                break
        return max_score


class process:
    @staticmethod
    def extractOne(query, choices, scorer=None):
        if scorer is None:
            scorer = fuzz.ratio
        best_choice = None
        best_score = -1
        for choice in choices or []:
            score = scorer(query, choice)
            if score > best_score:
                best_score = score
                best_choice = choice
        if best_choice is None:
            return None
        return best_choice, best_score
