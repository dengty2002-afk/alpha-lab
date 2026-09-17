import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from quant_platform.worker import dispatch


def test_fixture_analysis_and_three_models(tmp_path):
    project=Path(__file__).resolve().parents[2]
    workspace=tmp_path/"研究 workspace"
    events=[]
    def emit(event,**kwargs): events.append({"type":event,**kwargs})
    def run(kind,config):
        directory=workspace/"runs"/str(len(events))
        return dispatch({"schemaVersion":"1.0","jobId":directory.name,"type":kind,"config":config,
                         "projectDir":str(project),"workspaceDir":str(workspace),"runDir":str(directory)},emit),directory
    fixture,_=run("GENERATE_FIXTURE",{"instrumentCount":25,"startDate":"2022-09-01","endDate":"2025-03-31"})
    sid=fixture["summary"]["snapshotId"]
    spec={"name":"Momentum","expression":"$close/Ref($close,20)-1","direction":1}
    analysis,path=run("FACTOR_ANALYSIS",{"snapshotId":sid,"factor":spec,"startDate":"2025-01-01","endDate":"2025-03-31",
                                        "horizons":[1,5],"rebalancePeriods":[1,5],"costBps":[0,10]})
    assert analysis["summary"]["synthetic"]
    assert len(analysis["tables"]["horizons"])==2
    assert len(analysis["charts"]["series"])==8
    assert (path/"report.html").exists()
    assert not analysis["summary"]["marketBenchmarkAvailable"]
    assert all((path/a["path"]).is_file() for a in analysis["artifacts"])
    config={"snapshotId":sid,"factors":[spec,{"name":"Range","expression":"($high-$low)/$close","direction":-1}],
            "trainStart":"2022-10-01","trainEnd":"2023-12-31","validStart":"2024-01-01","validEnd":"2024-12-31",
            "testStart":"2025-01-01","testEnd":"2025-03-31","labelHorizon":5,"rebalancePeriods":[5],"costBps":[0,10],
            "modelParams":{"lightgbm":{"n_estimators":10}}}
    experiment,_=run("MODEL_EXPERIMENT",config)
    assert experiment["summary"]["modelCount"]==3
    assert len(experiment["tables"]["models"])==9
    assert len(experiment["tables"]["backtests"])==6
    json.dumps(experiment,allow_nan=False)


def test_stdout_json_protocol_and_failure(tmp_path):
    project=Path(__file__).resolve().parents[2]
    run=tmp_path/"runs"/"中文任务"
    run.mkdir(parents=True)
    job={"schemaVersion":"1.0","jobId":"中文任务","type":"FACTOR_PREVIEW","config":{"snapshotId":"missing"},
         "projectDir":str(project),"workspaceDir":str(tmp_path),"runDir":str(run)}
    file=run/"job.json"
    file.write_text(json.dumps(job),encoding="utf-8")
    env={**os.environ,"PYTHONPATH":str(project/"research"/"src"),"PYTHONUTF8":"1"}
    process=subprocess.run([sys.executable,"-m","quant_platform.worker","--job-file",str(file)],env=env,capture_output=True,encoding="utf-8")
    events=[json.loads(line) for line in process.stdout.splitlines()]
    assert process.returncode!=0
    assert events[-1]["type"]=="error"
    assert [e["seq"] for e in events]==list(range(1,len(events)+1))
    assert not (run/"result.json").exists()
