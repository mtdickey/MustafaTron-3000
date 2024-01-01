from groupy.client import Client
from groupy.api.bots import Bot


def post_image(client: Client,
               bot: Bot,
               path: str, caption: str):
    """
    Post an image with text to a GroupMe

    Args:
        client (Client): Groupy client connection
        bot (Bot): Groupy bot object
        path (str): Path to the image
        caption (str): Caption text
    """
    with open(path, 'rb') as f:
        image = client.images.from_file(f)

    bot.post(text = caption, attachments = [image])


def post_all_reports(client: Client, bot: Bot, image_paths: list, captions: list):
    """
    Iterate through a list of report images/captions and post them all.
    
    Args:
        image_paths (list): List of paths to each of the report images
        captions (list): List of captions to post with each image
    """
    for path, caption in zip(image_paths, captions):
        post_image(client, bot, path, caption)