import argparse
import tarfile
from collections import defaultdict
from nltk.tokenize import sent_tokenize

from sacrerouge.common.util import merge_dict
from sacrerouge.io import JsonlWriter


def parse_filename(filename: str):
    parts = filename.split('.')
    assert len(parts) == 5
    instance_id = parts[0].split('-')[0].lower()
    group = parts[0].split('-')[1]
    summarizer_id = parts[4]
    return instance_id, group, summarizer_id


def load_summaries(eval_tar: str):
    summaries = defaultdict(lambda: defaultdict(dict))
    with tarfile.open(eval_tar, 'r') as tar:
        for member in tar.getmembers():
            if member.isfile() and (member.name.startswith('UpdateSumm09_eval/ROUGE/models/') or member.name.startswith('UpdateSumm09_eval/ROUGE/peers/')):
                path = member.name.split('/')
                filename = path[-1]
                instance_id, group, summarizer_id = parse_filename(filename)

                if summarizer_id.isalpha():
                    summarizer_type = 'reference'
                else:
                    summarizer_type = 'peer'

                text = tar.extractfile(member).read().decode(errors='replace').strip()
                sentences = sent_tokenize(text)
                summary = {
                    'summarizer_id': summarizer_id,
                    'summarizer_type': summarizer_type,
                    'text': sentences
                }
                summaries[instance_id][summarizer_id][group] = summary
    return summaries


def load_manual_judgments(eval_tar: str):
    judgments = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    with tarfile.open(eval_tar, 'r') as tar:
        for filename in ['manual.model.A', 'manual.model.B']:
            lines = tar.extractfile(f'UpdateSumm09_eval/manual/{filename}').read().decode().splitlines()
            for line in lines:
                columns = line.split()
                instance_id = columns[0].split('-')[0].lower()
                group = columns[0].split('-')[1]
                summarizer_id = columns[1]
                judgments[instance_id][group][summarizer_id] = {
                    'num_scus_jk': int(columns[2]),
                    'modified_pyramid_score_jk': float(columns[5]),
                    'linguistic_quality': int(columns[6]),
                    'overall_responsiveness': int(columns[7])
                }

        for filename in ['manual.peer.A', 'manual.peer.B']:
            lines = tar.extractfile(f'UpdateSumm09_eval/manual/{filename}').read().decode().splitlines()
            for line in lines:
                columns = line.split()
                instance_id = columns[0].split('-')[0].lower()
                group = columns[0].split('-')[1]
                summarizer_id = columns[1]
                judgments[instance_id][group][summarizer_id] = {
                    'modified_pyramid_score': float(columns[2]),
                    'num_scus': int(columns[3]),
                    'num_repetitions': int(columns[4]),
                    'modified_pyramid_score_jk': float(columns[7]),
                    'linguistic_quality': int(columns[8]),
                    'overall_responsiveness': int(columns[9])
                }
    return judgments


def load_rouge_output(eval_tar: str, file_path1: str, file_path2: str):
    metrics = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    with tarfile.open(eval_tar, 'r') as tar:
        for file_path in [file_path1, file_path2]:
            lines = tar.extractfile(file_path).read().decode().splitlines()
            for line in lines:
                columns = line.split()
                if len(columns) == 7 and columns[2] == 'Eval':
                    summarizer_id = columns[0]
                    rouge_metric = columns[1].lower()
                    instance_id, group, summarizer_id = parse_filename(columns[3])
                    recall = float(columns[4][2:]) * 100
                    precision = float(columns[5][2:]) * 100
                    f1 = float(columns[6][2:]) * 100
                    metrics[instance_id][group][summarizer_id][rouge_metric] = {
                        'recall': recall,
                        'precision': precision,
                        'f1': f1
                    }
    return metrics


def load_rouge_jk_output(eval_tar: str, file_path1: str, file_path2: str):
    jk_metrics = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(list)))))
    with tarfile.open(eval_tar, 'r') as tar:
        for file_path in [file_path1, file_path2]:
            lines = tar.extractfile(file_path).read().decode().splitlines()
            for line in lines:
                columns = line.split()
                if len(columns) == 7 and columns[2] == 'Eval':
                    summarizer_id = columns[0]
                    rouge_metric = columns[1].lower() + '_jk'
                    instance_id, group, summarizer_id = parse_filename(columns[3])

                    recall = float(columns[4][2:]) * 100
                    precision = float(columns[5][2:]) * 100
                    f1 = float(columns[6][2:]) * 100
                    jk_metrics[instance_id][group][summarizer_id][rouge_metric]['recall'].append(recall)
                    jk_metrics[instance_id][group][summarizer_id][rouge_metric]['precision'].append(precision)
                    jk_metrics[instance_id][group][summarizer_id][rouge_metric]['f1'].append(f1)

            metrics = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
            for instance_id in jk_metrics.keys():
                for group in ['A', 'B']:
                    for summarizer_id in jk_metrics[instance_id][group].keys():
                        for rouge_metric in jk_metrics[instance_id][group][summarizer_id].keys():
                            recalls = jk_metrics[instance_id][group][summarizer_id][rouge_metric]['recall']
                            precisions = jk_metrics[instance_id][group][summarizer_id][rouge_metric]['precision']
                            f1s = jk_metrics[instance_id][group][summarizer_id][rouge_metric]['f1']
                            metrics[instance_id][group][summarizer_id][rouge_metric] = {
                                'recall': sum(recalls) / len(recalls),
                                'precision': sum(precisions) / len(precisions),
                                'f1': sum(f1s) / len(f1s)
                            }
    return metrics


def load_aesop_metrics(aesop_tar: str):
    metrics = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(dict))))
    with tarfile.open(aesop_tar, 'r') as tar:
        for member in tar.getmembers():
            for group, filename in zip(['A', 'B'], ['AESOP09_eval/data/aesop_allpeers_A', 'AESOP09_eval/data/aesop_allpeers_B']):
                lines = tar.extractfile(filename).read().decode().splitlines()
                for line in lines[1:]:
                    columns = line.split()
                    summarizer_id = columns[0][1:]
                    instance_number = int(columns[1][1:])
                    instance_id = 'd0' + str(900 + instance_number)
                    for i, value in enumerate(columns[2:]):
                        if value != 'NaN':
                            metrics[instance_id][group][summarizer_id]['aesop'][str(i + 1)] = float(value)

    return metrics


def get_references(summaries, instance_id, summarizer_id, group):
    summarizer_ids = list(summaries[instance_id].keys())
    reference_ids = list(filter(lambda sid: sid.isalpha(), summarizer_ids))

    references = []
    for reference_id in reference_ids:
        if summarizer_id == reference_id:
            continue
        references.append(summaries[instance_id][reference_id][group])
    return references


def save_summaries_and_metrics(summaries, metrics, output_dir: str):
    with JsonlWriter(f'{output_dir}/task1.A-B.summaries.jsonl') as out_summaries_A_B:
        with JsonlWriter(f'{output_dir}/task1.A.summaries.jsonl') as out_summaries_A:
            with JsonlWriter(f'{output_dir}/task1.B.summaries.jsonl') as out_summaries_B:
                with JsonlWriter(f'{output_dir}/task1.A-B.metrics.jsonl') as out_metrics_A_B:
                    with JsonlWriter(f'{output_dir}/task1.A.metrics.jsonl') as out_metrics_A:
                        with JsonlWriter(f'{output_dir}/task1.B.metrics.jsonl') as out_metrics_B:
                            for instance_id in sorted(summaries.keys()):
                                for summarizer_id in sorted(summaries[instance_id].keys()):
                                    summary_A = summaries[instance_id][summarizer_id]['A']
                                    summary_B = summaries[instance_id][summarizer_id]['B']

                                    references_A = get_references(summaries, instance_id, summarizer_id, 'A')
                                    references_B = get_references(summaries, instance_id, summarizer_id, 'B')

                                    metrics_A = metrics[instance_id]['A'][summarizer_id]
                                    metrics_B = metrics[instance_id]['B'][summarizer_id]

                                    summary_instance_A = {
                                        'instance_id': f'{instance_id}-A',
                                        'summarizer_id': summarizer_id,
                                        'summarizer_type': summary_A['summarizer_type'],
                                        'summary': summary_A,
                                        'references': references_A,
                                    }
                                    summary_instance_B = {
                                        'instance_id': f'{instance_id}-B',
                                        'summarizer_id': summarizer_id,
                                        'summarizer_type': summary_B['summarizer_type'],
                                        'summary': summary_B,
                                        'references': references_B,
                                        'metrics': metrics_B
                                    }
                                    metric_instance_A = {
                                        'instance_id': f'{instance_id}-A',
                                        'summarizer_id': summarizer_id,
                                        'summarizer_type': summary_A['summarizer_type'],
                                        'metrics': metrics_A
                                    }
                                    metric_instance_B = {
                                        'instance_id': f'{instance_id}-B',
                                        'summarizer_id': summarizer_id,
                                        'summarizer_type': summary_B['summarizer_type'],
                                        'metrics': metrics_B
                                    }

                                    out_summaries_A_B.write(summary_instance_A)
                                    out_summaries_A_B.write(summary_instance_B)
                                    out_summaries_A.write(summary_instance_A)
                                    out_summaries_B.write(summary_instance_B)

                                    out_metrics_A_B.write(metric_instance_A)
                                    out_metrics_A_B.write(metric_instance_B)
                                    out_metrics_A.write(metric_instance_A)
                                    out_metrics_B.write(metric_instance_B)


def setup(data_dir: str, output_dir: str):
    eval_tar = f'{data_dir}/scrapes/tac.nist.gov/protected/past-aquaint2/2009/UpdateSumm09_eval.tar.gz'
    aesop_tar = f'{data_dir}/scrapes/tac.nist.gov/protected/past-aquaint2/2009/AESOP09_eval.tar.gz'
    main(eval_tar, aesop_tar, output_dir)


def main(eval_tar, aesop_tar, output_dir):
    summaries = load_summaries(eval_tar)
    judgments = load_manual_judgments(eval_tar)
    rouge = load_rouge_output(eval_tar, 'UpdateSumm09_eval/ROUGE/rouge_A.m.out', 'UpdateSumm09_eval/ROUGE/rouge_B.m.out')
    rouge_jk = load_rouge_jk_output(eval_tar, 'UpdateSumm09_eval/ROUGE/rougejk_A.m.out', 'UpdateSumm09_eval/ROUGE/rougejk_B.m.out')
    be = load_rouge_output(eval_tar, 'UpdateSumm09_eval/BE/simple_A.m.hm.out', 'UpdateSumm09_eval/BE/simple_B.m.hm.out')
    be_jk = load_rouge_jk_output(eval_tar, 'UpdateSumm09_eval/BE/simplejk_A.m.hm.out', 'UpdateSumm09_eval/BE/simplejk_B.m.hm.out')
    aesop = load_aesop_metrics(aesop_tar)

    metrics = judgments
    merge_dict(metrics, rouge)
    merge_dict(metrics, rouge_jk)
    merge_dict(metrics, be)
    merge_dict(metrics, be_jk)
    merge_dict(metrics, aesop)

    save_summaries_and_metrics(summaries, metrics, output_dir)


if __name__ == '__main__':
    argp = argparse.ArgumentParser()
    argp.add_argument('eval_tar')
    argp.add_argument('aesop_tar')
    argp.add_argument('output_dir')
    args = argp.parse_args()

    main(args.eval_tar, args.aesop_tar, args.output_dir)
