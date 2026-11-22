"""Record a result from a regional council's public registry using operator DB access."""

import argparse
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.session import get_engine
from app.models.crefito_review import CrefitoResult
from app.repositories.crefito_reviews import pending_reviews
from app.services.crefito_reviews import PUBLIC_REGISTRIES, pending_review, record_result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("pending", help="List up to 100 pending review IDs")
    show = commands.add_parser("show", help="Display the registry URL and registration to check")
    show.add_argument("review_id", type=UUID)
    record = commands.add_parser("record", help="Record the outcome of a completed manual check")
    record.add_argument("review_id", type=UUID)
    record.add_argument("result", type=CrefitoResult, choices=list(CrefitoResult))
    record.add_argument("--reviewer-id", type=UUID, required=True)
    args = parser.parse_args()

    try:
        with Session(get_engine()) as db:
            if args.command == "pending":
                for review_id in pending_reviews(db, 100):
                    print(review_id)
            elif args.command == "show":
                professional, _ = pending_review(db, str(args.review_id))
                print(PUBLIC_REGISTRIES[professional.crefito_region])
                print(f"CREFITO-{professional.crefito_region} / {professional.crefito_number}")
            else:
                record_result(db, str(args.review_id), args.result, str(args.reviewer_id))
                print("Review recorded")
    except ValueError as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
