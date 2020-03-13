import os
import re
from collections import Counter
from nltk.stem import PorterStemmer
from typing import Dict, List, Optional, Set, Tuple

from sacrerouge.data.types import MetricsType, SummaryType
from sacrerouge.metrics import Metric


def shorten_summary(summary: SummaryType,
                    max_sentences: Optional[int] = None,
                    max_words: Optional[int] = None,
                    max_bytes: Optional[int] = None) -> List[str]:
    args = [max_sentences, max_words, max_bytes]
    if sum(1 if arg is not None else 0 for arg in args) not in [0, 1]:
        raise Exception(f'Only one of `max_sentences`, `max_words`, and `max_bytes` can be set.')

    # Maybe wrap the summary into a sentence
    if isinstance(summary, str):
        summary = [summary]

    shortened_summary = []
    if max_sentences is not None:
        shortened_summary = summary[:max_sentences]
    elif max_words is not None:
        budget = max_words
        for sentence in summary:
            tokens = sentence.split()[:budget]
            shortened_summary.append(' '.join(tokens))
            budget -= len(tokens)
            if budget <= 0:
                break
    elif max_bytes is not None:
        budget = max_bytes
        for sentence in summary:
            sentence = sentence[:budget].strip()
            shortened_summary.append(sentence)
            budget -= len(sentence)
            if budget <= 0:
                break
    else:
        shortened_summary = summary

    return shortened_summary


@Metric.register('python-rouge')
class PythonRouge(Metric):
    _non_alphanumeric_regex = re.compile('[^A-Za-z0-9]')

    def __init__(self,
                 ngram_orders: List[int] = [1, 2],
                 max_sentences: Optional[int] = None,
                 max_words: Optional[int] = None,
                 max_bytes: Optional[int] = None,
                 use_porter_stemmer: bool = True,
                 remove_stopwords: bool = False,
                 compute_rouge_l: bool = False,
                 data_dir: str = 'external/ROUGE-1.5.5/data'):
        super().__init__()
        self.ngram_orders = ngram_orders
        self.max_sentences = max_sentences
        self.max_words = max_words
        self.max_bytes = max_bytes
        self.use_porter_stemmer = use_porter_stemmer
        self.remove_stopwords = remove_stopwords
        self.compute_rouge_l = compute_rouge_l

        self.stemmer = PorterStemmer(PorterStemmer.ORIGINAL_ALGORITHM)
        self.stemmer_exceptions = self._load_stemmer_exceptions(data_dir)
        self.stopwords = self._load_stopwords(data_dir)

    def _load_stemmer_exceptions(self, root: str) -> Dict[str, str]:
        exceptions = {}
        for filename in ['adj.exc', 'adv.exc', 'noun.exc', 'verb.exc']:
            file_path = os.path.join(root, 'WordNet-2.0-Exceptions', filename)
            with open(file_path, 'r') as f:
                for line in f:
                    # I think there is a bug in the original perl script
                    # to construct the exceptions database. Some of the lines
                    # have more than 2 words on them, but the script only
                    # maps the first to the second, ignoring the third.
                    columns = line.strip().split()
                    exceptions[columns[0]] = columns[1]
        return exceptions

    def _load_stopwords(self, root: str) -> Set[str]:
        file_path = os.path.join(root, 'smart_common_words.txt')
        return set(open(file_path, 'r').read().splitlines())

    def normalize_and_tokenize_sentence(self, sentence: str) -> List[str]:
        sentence = PythonRouge._non_alphanumeric_regex.sub(' ', sentence)
        sentence = sentence.lower()
        tokens = []
        for token in sentence.split():
            if self.remove_stopwords and token in self.stopwords:
                continue
            if self.use_porter_stemmer and len(token) > 3:
                if token in self.stemmer_exceptions:
                    tokens.append(self.stemmer_exceptions[token])
                else:
                    tokens.append(self.stemmer.stem(token))
            else:
                tokens.append(token)
        return tokens

    def _normalize_and_tokenize_summary(self, summary: List[str]) -> List[str]:
        return [self.normalize_and_tokenize_sentence(sentence) for sentence in summary]

    def preprocess_summary(self, summary: SummaryType) -> List[List[str]]:
        summary = shorten_summary(summary, self.max_sentences, self.max_words, self.max_bytes)
        summary = self._normalize_and_tokenize_summary(summary)
        return summary

    def _count_ngrams(self, summary: SummaryType, n: int) -> Counter:
        counts = Counter()
        if isinstance(summary, str):
            summary = [summary]
        tokens = [token for sentence in summary for token in sentence]
        for i in range(len(tokens) - n + 1):
            ngram = ' '.join(tokens[i:i + n])
            counts[ngram] += 1
        return counts

    def _calculate_intersection(self, reference_counts: Counter, summary_counts: Counter) -> Tuple[float, float, float]:
        reference_total = sum(reference_counts.values())
        summary_total = sum(summary_counts.values())
        intersection = 0
        for ngram in summary_counts:
            intersection += min(summary_counts[ngram], reference_counts[ngram])
        return reference_total, summary_total, intersection

    def _calculate_pr_f1(self, reference_total: int, summary_total: int, intersection: int) -> Tuple[float, float, float]:
        precision = 0.0
        if summary_total != 0.0:
            precision = intersection / summary_total * 100
        recall = 0.0
        if reference_total != 0.0:
            recall = intersection / reference_total * 100
        if precision + recall == 0:
            f1 = 0.0
        else:
            f1 = 2 * (precision * recall) / (precision + recall)
        return precision, recall, f1

    def _longest_common_substring(self,
                                  tokens1: List[str],
                                  tokens2: List[str],
                                  hit_mask: List[int]) -> int:
        m, n = len(tokens1), len(tokens2)
        counter = [[0] * (n + 1) for x in range(m + 1)]
        pointers = [[None] * (n + 1) for x in range(m + 1)]
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if tokens1[i - 1] == tokens2[j - 1]:
                    counter[i][j] = counter[i - 1][j - 1] + 1
                    pointers[i][j] = '\\'
                elif counter[i - 1][j] >= counter[i][j - 1]:
                    counter[i][j] = counter[i - 1][j]
                    pointers[i][j] = '^'
                else:
                    counter[i][j] = counter[i][j - 1]
                    pointers[i][j] = '<'

        # Mark the hit_mask
        i, j = m, n
        while i != 0 and j != 0:
            if pointers[i][j] == '\\':
                i -= 1
                j -= 1
                hit_mask[i] = 1
            elif pointers[i][j] == '^':
                i -= 1
            elif pointers[i][j] == '<':
                j -= 1
            else:
                raise Exception(f'Unknown pointer: {pointers[i][j]}')

    def _calculate_rouge_l(self,
                           references: List[SummaryType],
                           summary: SummaryType):
        model_unigrams = self._count_ngrams(summary, 1)
        num_model_unigrams = sum(count for count in model_unigrams.values())

        if isinstance(summary, str):
            summary = [summary]
        references = [[reference] if isinstance(reference, str) else reference for reference in references]

        total_hit = 0
        total_base = 0
        for reference in references:
            temp_model_unigrams = Counter(model_unigrams)
            gold_unigrams = self._count_ngrams(reference, 1)
            hit, base = 0, 0
            for ref_sentence in reference:
                hit_mask = [0] * len(ref_sentence)
                base += len(ref_sentence)
                for model_sentence in summary:
                    self._longest_common_substring(ref_sentence, model_sentence, hit_mask)

                for i, token in enumerate(ref_sentence):
                    if hit_mask[i] == 1:
                        try:
                            if temp_model_unigrams[token] > 0 and gold_unigrams[token] > 0:
                                hit += 1
                                temp_model_unigrams[token] -= 1
                                gold_unigrams[token] -= 1
                        except KeyError:
                            pass
            total_hit += hit
            total_base += base

        precision = 0.0
        if (num_model_unigrams * len(references)) != 0.0:
            precision = total_hit / (num_model_unigrams * len(references)) * 100
        recall = 0.0
        if total_base != 0.0:
            recall = total_hit / total_base * 100
        if (precision + recall) != 0.0:
            f1 = 2 * (precision * recall) / (precision + recall)
        else:
            f1 = 0.0
        return precision, recall, f1

    def score(self,
              summary: SummaryType,
              references: List[SummaryType]) -> MetricsType:
        summary = self.preprocess_summary(summary)
        references = [self.preprocess_summary(reference) for reference in references]

        metrics = {}
        for n in self.ngram_orders:
            total_reference_count = 0
            total_summary_count = 0
            total_intersection = 0

            summary_ngrams = self._count_ngrams(summary, n)
            for reference in references:
                reference_ngrams = self._count_ngrams(reference, n)
                reference_total, summary_total, intersection = self._calculate_intersection(reference_ngrams, summary_ngrams)

                total_reference_count += reference_total
                total_summary_count += summary_total
                total_intersection += intersection

            precision, recall, f1 = self._calculate_pr_f1(total_reference_count, total_summary_count, total_intersection)
            metrics[f'python-rouge-{n}'] = {
                'precision': precision,
                'recall': recall,
                'f1': f1,
            }

        if self.compute_rouge_l:
            precision, recall, f1 = self._calculate_rouge_l(references, summary)
            metrics['python-rouge-l'] = {
                'precision': precision,
                'recall': recall,
                'f1': f1
            }
        return metrics