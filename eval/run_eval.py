"""Платный eval настоящей LLM. Запуск: .venv/bin/python -m eval.run_eval."""
import asyncio
import hashlib
import json
import subprocess
import tempfile
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from app.agent import SYSTEM_PROMPT, run_agent
from app.llm import ChatModel
from app.mcp_client import PROJECT_ROOT, connect_mcp

SEED = [
    {'title':'Рифф для куплета','description':'Попробовать перегруз','instrument':'Гитара','mood':'Мрачное','bpm':95},
    {'title':'Рифф для припева','instrument':'Гитара','mood':'Энергичное','bpm':130},
    {'title':'Тихая мелодия','instrument':'Фортепиано','mood':'Спокойное','bpm':75},
    {'title':'Без темпа','instrument':'Гитара','mood':'Спокойное'},
    {'title':'Барабанный грув','instrument':'Барабаны','mood':'Энергичное','bpm':110},
]

class CountedModel:
    def __init__(self, model):
        self.model = model
        self.calls = 0
    async def complete(self, messages, tools):
        self.calls += 1
        return await self.model.complete(messages, tools)

async def evaluate(case, model, directory):
    wrapped = CountedModel(model)
    started = time.monotonic()
    record = {'case':case, 'checks':{}, 'result':None, 'error':None}
    async with connect_mcp(directory / (case['id'] + '.sqlite3')) as client:
        for idea in SEED:
            saved = await client.call_tool('create_idea', idea)
            if saved.isError:
                raise RuntimeError('Не удалось создать тестовые данные')
        before = (await client.call_tool('search_ideas', {})).structuredContent['ideas']
        try:
            result = await run_agent(case['query'], wrapped, client)
            record['result'] = asdict(result)
            checks = record['checks']
            checks['answer_not_empty'] = bool(result.answer.strip())
            after = (await client.call_tool('search_ideas', {})).structuredContent['ideas']
            checks['no_change_before_confirmation'] = before == after
            kind = case['kind']
            if kind == 'search':
                searches = [s for s in result.trace if s['tool']=='search_ideas' and not s['is_error']]
                checks['search_called'] = bool(searches)
                actual = {i['title'] for i in searches[-1]['result']['ideas']} if searches else None
                checks['exact_result_set'] = actual == set(case['titles'])
                checks['no_write_proposed'] = result.pending_create is None and result.pending_delete is None
            elif kind == 'create':
                proposal = result.pending_create
                checks['create_proposed'] = proposal is not None and result.pending_delete is None
                checks['explicit_fields'] = proposal is not None and all(proposal.get(k)==v for k,v in case['fields'].items())
                checks['unknown_fields_empty'] = proposal is not None and all(proposal.get(k) in (None,'') for k in case.get('unknown',[]))
                if proposal is not None:
                    # Имитируем явное подтверждение только на временной библиотеке.
                    saved = await client.call_tool('create_idea', proposal)
                    checks['confirmation_creates_card'] = not saved.isError
            elif kind == 'delete':
                proposal = result.pending_delete
                checks['correct_delete_proposed'] = proposal is not None and proposal['title']==case['title'] and result.pending_create is None
                if proposal is not None:
                    # Отмена: не вызываем удаление, запись должна по-прежнему существовать.
                    found = await client.call_tool('get_idea', {'idea_id':proposal['id']})
                    checks['cancel_preserves_card'] = found.structuredContent['found']
                    deleted = await client.call_tool('delete_idea', {'idea_id':proposal['id']})
                    remaining = (await client.call_tool('search_ideas', {})).structuredContent['ideas']
                    checks['confirmation_deletes_only_selected'] = deleted.structuredContent['deleted'] and {i['id'] for i in remaining} == {i['id'] for i in before if i['id']!=proposal['id']}
            elif kind == 'clarify':
                checks['no_delete_proposed'] = result.pending_delete is None and result.pending_create is None
                checks['question_present'] = '?' in result.answer
        except Exception as error:
            # Сообщение наружу не выводим: оно может содержать данные провайдера.
            record['error'] = type(error).__name__
    record['model_calls'] = wrapped.calls
    record['seconds'] = round(time.monotonic()-started,2)
    record['passed'] = record['error'] is None and bool(record['checks']) and all(record['checks'].values())
    return record

async def main():
    load_dotenv(PROJECT_ROOT / '.env')
    model = ChatModel.from_env()
    folder = PROJECT_ROOT / 'eval'
    cases = json.loads((folder / 'cases.json').read_text())
    report = {'started_at':datetime.now(timezone.utc).isoformat(), 'model':model.model,
              'git_revision':subprocess.check_output(['git','rev-parse','HEAD'],text=True,cwd=PROJECT_ROOT).strip(),
              'prompt_sha256':hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
              'repeats_per_case':1, 'seed':SEED, 'cases':[]}
    with tempfile.TemporaryDirectory(prefix='music-eval-') as directory:
        for case in cases:
            record = await evaluate(case, model, Path(directory))
            report['cases'].append(record)
            (folder / 'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
            print(('PASS' if record['passed'] else 'FAIL')+' '+case['id']+' '+str(record['seconds'])+'s',flush=True)
    report['passed'] = sum(c['passed'] for c in report['cases'])
    report['total'] = len(cases)
    report['model_calls'] = sum(c['model_calls'] for c in report['cases'])
    (folder / 'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(f"Итого: {report['passed']}/{report['total']}; обращений к модели: {report['model_calls']}")

if __name__ == '__main__':
    asyncio.run(main())
