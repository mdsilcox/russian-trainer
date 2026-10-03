"""Task helpers for T-S (appended to the common conftest; import as conftest_task)."""

from datetime import datetime, timedelta, timezone

from sqlmodel import select


def make_card(session, ru="слово", en="word", rec=0, prod=None, suspended=False, due_past=False, **fields):
    """Create a card through the service; set recognition lapses to `rec`, add a production
    schedule with `prod` lapses when given. Reviewed (state 2) and long overdue when `due_past`."""
    from app.models import CardState, Direction
    from app.services import cards

    card = cards.create_card(session, ru=ru, en=en, **fields)
    states = {Direction.recognition: session.exec(select(CardState).where(CardState.card_id == card.id)).one()}
    if prod is not None:
        production = CardState(card_id=card.id, direction=Direction.production)
        session.add(production)
        session.commit()
        states[Direction.production] = production
    lapses = {Direction.recognition: rec, Direction.production: prod or 0}
    long_ago = datetime.now(timezone.utc) - timedelta(days=400)
    for direction, cs in states.items():
        cs.lapses = lapses[direction]
        if due_past:
            cs.state = 2
            cs.stability = 10.0
            cs.difficulty = 5.0
            cs.step = None
            cs.reps = 10
            cs.last_review = long_ago - timedelta(days=30)
            cs.due = long_ago
        session.add(cs)
    if suspended:
        card.suspended = True
        session.add(card)
    session.commit()
    session.refresh(card)
    return card
