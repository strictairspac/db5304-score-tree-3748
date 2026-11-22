from fastapi import APIRouter, Depends
from sqlalchemy import text

from src.config.settings import cache, engine
from src.controllers.workflow import download
from src.models.tables import audit, cases, evidence, runs
from src.schemas.workflow import CaseForm, LoginForm, OrderForm, ReviewForm
from src.services import domain, lending, workflow
from src.services.security import current_user, login, operator, reviewer

router = APIRouter()


@router.get('/health')
def health():
    with engine.connect() as conn:
        conn.execute(text('SELECT 1')).scalar_one()
    cache.ping()
    return {'ok': True}


@router.post('/login')
def sign_in(form: LoginForm):
    return login(form.username, form.password)


@router.get('/spec')
def spec(_=Depends(current_user)):
    return domain.SPEC


@router.get('/cases')
def list_cases(_=Depends(current_user)):
    return workflow.recent(cases)


@router.post('/cases', status_code=201)
def create_case(form: CaseForm, actor=Depends(operator)):
    return workflow.make_case(form.title, form.payload, actor)


@router.get('/runs')
def list_runs(_=Depends(current_user)):
    return workflow.recent(runs)


@router.post('/cases/{case_id}/runs', status_code=202)
def start_run(case_id: int, actor=Depends(operator)):
    return workflow.enqueue(case_id, actor)


@router.get('/evidence')
def list_evidence(_=Depends(current_user)):
    return workflow.recent(evidence)


@router.get('/evidence/{identity}/download')
def export_evidence(identity: int, _=Depends(current_user)):
    return download(identity)


@router.post('/evidence/{identity}/review')
def review_evidence(identity: int, form: ReviewForm, actor=Depends(reviewer)):
    return workflow.review(identity, form.note, actor)


@router.get('/lending/orders')
def list_lending_orders(_=Depends(current_user)):
    return lending.list_orders()


@router.get('/lending/orders/{identity}')
def get_lending_order(identity: int, _=Depends(current_user)):
    return lending.get_order(identity)


@router.post('/lending/orders', status_code=201)
def create_lending_order(form: OrderForm, actor=Depends(operator)):
    return lending.create_order(form.case_id, form.start_number, form.end_number,
                                form.request_key, actor)


@router.post('/lending/orders/{identity}/cancel')
def cancel_lending_order(identity: int, actor=Depends(operator)):
    return lending.cancel_order(identity, actor)


@router.get('/lending/inventory/{case_id}')
def read_lending_inventory(case_id: int, _=Depends(current_user)):
    return lending.inventory(case_id)


@router.get('/audit')
def list_audit(_=Depends(current_user)):
    return workflow.recent(audit)
