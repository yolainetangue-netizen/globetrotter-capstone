# -*- coding: utf-8 -*-
"""
GlobeTrotter - Phase 2 - Event Consumer (demonstration)
Petit service independant qui ECOUTE la file RabbitMQ et reagit aux
evenements publies par l'Itinerary Service (ex: "itinerary.created").

Ceci demontre concretement la communication ASYNCHRONE demandee par
le cahier des charges : l'Itinerary Service ne sait pas qui consomme
cet evenement, ni combien de temps ca prendra - c'est le principe
du decouplage par file de messages.

Dans un vrai systeme, ce consommateur pourrait envoyer un email de
confirmation, invalider un cache de recommandations, etc. Ici, il se
contente d'ecrire chaque evenement recu dans un journal (events.log)
pour prouver que la chaine fonctionne bout en bout.
"""
import json
import os
import time

import pika

RABBITMQ_HOST = os.environ.get("RABBITMQ_HOST", "rabbitmq")
QUEUE_NAME = "itinerary_events"
LOG_FILE = os.path.join(os.path.dirname(__file__), "events.log")


def handle_message(ch, method, properties, body):
    event = json.loads(body)
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Evenement recu : {event['event']} -> {event['data']}\n"
    print(line, end="")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line)
    ch.basic_ack(delivery_tag=method.delivery_tag)


def main():
    print("[event-consumer] Connexion a RabbitMQ...")
    while True:
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
            channel = connection.channel()
            channel.queue_declare(queue=QUEUE_NAME, durable=True)
            channel.basic_consume(queue=QUEUE_NAME, on_message_callback=handle_message)
            print("[event-consumer] En ecoute sur la file 'itinerary_events'...")
            channel.start_consuming()
        except Exception as exc:
            print(f"[event-consumer] Connexion echouee ({exc}), nouvelle tentative dans 5s...")
            time.sleep(5)


if __name__ == "__main__":
    main()
