import asyncio
import json

import aioredis
import async_timeout
from pydantic import BaseModel
from fastapi import FastAPI

from worker import celery

app = FastAPI()


class Item(BaseModel):
    name: str


@app.post("/task_hello_world/")
async def create_item(item: Item):
    task_name = "hello.task"
    task = celery.send_task(task_name, args=[item.name])
    return dict(id=task.id, url='localhost:5000/check_task/{}'.format(task.id))


@app.get("/check_task/{id}")
def check_task(id: str):
    task = celery.AsyncResult(id)
    if task.state == 'SUCCESS':
        response = {
            'status': task.state,
            'result': task.result,
            'task_id': id
        }
    elif task.state == 'FAILURE':
        response = json.loads(task.backend.get(task.backend.get_key_for_task(task.id)).decode('utf-8'))
        del response['children']
        del response['traceback']
    else:
        response = {
            'status': task.state,
            'result': task.info,
            'task_id': id
        }
    return response


@app.get("/send_event")
async def send_event(message: str):
    await main()
    return {"message": "send successfully!"}


async def pubsub():
    redis = aioredis.Redis.from_url(
        "redis://redis", max_connections=10, decode_responses=True
    )
    psub = redis.pubsub()

    async def reader(channel: aioredis.client.PubSub):
        while True:
            try:
                async with async_timeout.timeout(1):
                    message = await channel.get_message(ignore_subscribe_messages=True)
                    if message is not None:
                        print(f"(Reader) Message Received: {message}")
                        if message["data"] == "STOP":
                            print("(Reader) STOP")
                            break
                    await asyncio.sleep(0.01)
            except asyncio.TimeoutError:
                pass

    async with psub as p:
        await p.subscribe("channel:1")
        await reader(p)  # wait for reader to complete
        await p.unsubscribe("channel:1")

    # closing all open connections
    await psub.close()


async def main():
    tsk = asyncio.create_task(pubsub())

    async def publish():
        pub = aioredis.Redis.from_url("redis://redis", decode_responses=True)
        while not tsk.done():
            # wait for clients to subscribe
            while True:
                subs = dict(await pub.pubsub_numsub("channel:1"))
                if subs["channel:1"] == 1:
                    break
                await asyncio.sleep(0)
            # publish some messages
            for msg in ["one", "two", "three"]:
                print(f"(Publisher) Publishing Message: {msg}")
                await pub.publish("channel:1", msg)
            # send stop word
            await pub.publish("channel:1", "STOP")
        await pub.close()

    await publish()


@app.get("/init_receiver")
async def receiver():
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # 'RuntimeError: There is no current event loop...'
        loop = None

    if loop and loop.is_running():
        print('Async event loop already running. Adding coroutine to the event loop.')
        tsk = loop.create_task(main())
        # ^-- https://docs.python.org/3/library/asyncio-task.html#task-object
        # Optionally, a callback function can be executed when the coroutine completes
        tsk.add_done_callback(
            lambda t: print(f'Task done with result={t.result()}  << return val of main()'))
    else:
        print('Starting new event loop')
        result = asyncio.run(main())
    return {"message": "started successfully!"}
