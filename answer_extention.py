import json
import os
from tqdm import tqdm
import stanza
import logging
from utils import (
    INPUT_FILE,
    LOG_FORMAT,
    DATE_FORMAT,
    ENTITY_TYPES,
    SPAN_TYPES,
    DATA_DIR,
)

logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt=DATE_FORMAT)


PARSER = stanza.Pipeline(
    lang="vi",
    processors="tokenize, pos, constituency",
    use_gpu=True,
    device=0,
    verbose=False,
)

raws = {}
uid_sumidx2ans_range = {}

for span_type in SPAN_TYPES:
    logging.info("Logging span {}".format(span_type))
    with open(
        os.path.join(DATA_DIR, f"{INPUT_FILE}_answer_extract_{span_type}.json"),
        "r",
        encoding="utf-8",
    ) as f:
        raws[span_type] = json.load(f)
    uid_sumidx2ans_range[span_type] = {}

logging.info("Logging TVPL...")
with open(os.path.join(DATA_DIR, f"{INPUT_FILE}.json"), "r", encoding="utf-8") as f:
    tvpl = json.load(f)

uid2tvpl_data = {}
if not os.path.exists(os.path.join(DATA_DIR, "uid2tvpl_data.json")):
    logging.info("Process tvpl...")
    for item in tqdm(tvpl, desc="process tvpl"):
        uid = item["uid"]
        for sum_idx, sum_item in enumerate(item["summary"]):
            tokens = PARSER.parse(sum_item).leaves()
            sum_item = " ".join(tokens)
            item["summary"][sum_idx] = sum_item
        uid2tvpl_data[uid] = {
            "document": item["document"],
            "summary": item["summary"],
        }
    with open(os.path.join(DATA_DIR, "uid2tvpl_data.json"), "w", encoding="utf-8") as f:
        json.dump(uid2tvpl_data, f, indent=4)
else:
    logging.info("uid2tvpl_data exists! Logging...")
    with open(os.path.join(DATA_DIR, "uid2tvpl_data.json"), "r", encoding="utf-8") as f:
        uid2tvpl_data = json.load(f)

for span_type in SPAN_TYPES:
    for passage in tqdm(
        raws[span_type]["data"], desc="{} preprocess...".format(span_type)
    ):
        for p in passage["paragraphs"]:
            context = p["context"]
            for qa in p["qas"]:
                question = qa["question"]
                question = (
                    question.replace("(", "-LRB-")
                    .replace(")", "-RRB-")
                    .replace("[", "-LSB-")
                )
                question = (
                    question.replace("]", "-RSB-")
                    .replace("{", "-LCB-")
                    .replace("}", "-RCB-")
                )
                qid = qa["id"]
                uid = qid.split("_")[0]
                question_first_part = None
                question_second_part = None
                for entity_type in ENTITY_TYPES:
                    if len(question.split(entity_type)) > 1:
                        question_first_part = question.split(entity_type)[0]
                        question_second_part = question.split(entity_type)[1]
                        break
                assert (
                    question_first_part is not None and question_second_part is not None
                ), "q: {}, first: {}, second: {}".format(
                    question, question_first_part, question_second_part
                )
                summary = uid2tvpl_data[uid]["summary"]
                summary = [s.replace("(", "-LRB-") for s in summary]
                summary = [s.replace(")", "-RRB-") for s in summary]
                summary = [s.replace("[", "-LSB-") for s in summary]
                summary = [s.replace("]", "-RSB-") for s in summary]
                summary = [s.replace("{", "-LCB-") for s in summary]
                summary = [s.replace("}", "-RCB-") for s in summary]
                summary_idx = -1
                for sum_idx, summary_item in enumerate(summary):
                    if (
                        len(question_first_part) >= 1
                        and summary_item.find(question_first_part) != -1
                    ):
                        summary_idx = sum_idx
                        break
                    if (
                        len(question_second_part) >= 1
                        and summary_item.find(question_second_part) != -1
                    ):
                        summary_idx = sum_idx
                        break
                if (
                    summary_idx == -1
                    and len(question_first_part) == 0
                    and len(question_second_part) == 0
                ):
                    pass
                else:
                    assert (
                        summary_idx != -1
                    ), "qa: {}, summary: {}, first: ***{}***,***{}***; second: ****{}****,****{}****".format(
                        qa,
                        summary,
                        question_first_part,
                        question_second_part,
                        summary[0].find(question_first_part),
                        summary[0].find(question_second_part),
                    )
                qa["summary_idx"] = summary_idx
                answer = qa["answers"][0]
                answer_start = answer["answer_start"]
                answer_text = answer["text"]
                answer_end = answer_start + len(
                    answer_text
                )  # [answer_start, answer_end)
                if uid not in uid_sumidx2ans_range[span_type]:
                    uid_sumidx2ans_range[span_type][uid] = {}
                if summary_idx not in uid_sumidx2ans_range[span_type][uid]:
                    uid_sumidx2ans_range[span_type][uid][summary_idx] = []
                assert answer_text == context[answer_start:answer_end]
                uid_sumidx2ans_range[span_type][uid][summary_idx].append(
                    {
                        "question": question,
                        "text": answer_text,
                        "answer_start": answer_start,
                        "answer_end": answer_end,
                    }
                )

for passage in tqdm(raws["NE"]["data"], desc="extend NE answers..."):
    for p in passage["paragraphs"]:
        context = p["context"]
        for qa in p["qas"]:
            qid = qa["id"]
            uid = qid.split("_")[0]
            summary_idx = qa["summary_idx"]
            qa["answers"][0]["span_type"] = "NE"
            for entity_type in ENTITY_TYPES:
                if entity_type != "PLACEHOLDER" and entity_type in qa["question"]:
                    qa["answers"][0]["entity_type"] = entity_type
            if summary_idx == -1:
                continue
            answer_start = qa["answers"][0]["answer_start"]
            answer_end = answer_start + len(qa["answers"][0]["text"])
            for span_type in SPAN_TYPES:
                if span_type == "NE":
                    continue
                if uid not in uid_sumidx2ans_range[span_type]:
                    continue
                if summary_idx not in uid_sumidx2ans_range[span_type][uid]:
                    continue
                answer_ranges = uid_sumidx2ans_range[span_type][uid][summary_idx]
                for answer_range in answer_ranges:
                    if (
                        answer_range["answer_start"] < answer_start
                        and answer_range["answer_end"] >= answer_end
                        or answer_range["answer_start"] <= answer_start
                        and answer_range["answer_end"] > answer_end
                    ):
                        clause = qa["question"] + " " + qa["answers"][0]["text"]
                        clause_len = len(clause.split()) - 1  # ignore the placeholder
                        candidate_ans_len = len(answer_range["text"].split())
                        if clause_len * 0.8 < candidate_ans_len:
                            continue
                        qa["answers"][0]["span_type"] = span_type
                        qa["answers"][0]["answer_start"] = answer_range["answer_start"]
                        qa["answers"][0]["text"] = answer_range["text"]
                        qa["question"] = answer_range["question"].replace(
                            "PLACEHOLDER", qa["answers"][0]["entity_type"]
                        )
                        answer_start = answer_range["answer_start"]
                        answer_end = answer_range["answer_end"]
                        assert answer_range["text"] == context[answer_start:answer_end]

with open(
    os.path.join(DATA_DIR, "cloze_clause_tvpl _data_diverse_answer_span_80.json"),
    "w",
    encoding="utf-8",
) as f:
    json.dump(raws["NE"], f, indent=4)

raw = raws["NE"]

span2cnt = {}
for passage in tqdm(raw["data"], desc="span stat"):
    for p in passage["paragraphs"]:
        for qa in p["qas"]:
            ans_type = qa["answers"][0]["span_type"]
            if ans_type not in span2cnt:
                span2cnt[ans_type] = 1
            else:
                span2cnt[ans_type] += 1
logging.info(span2cnt)
