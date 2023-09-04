from PIL import Image

import visuals as viz
import data_utils as du

### TODO Create functions to stitch images together (from https://www.tutorialspoint.com/python_pillow/Python_pillow_merging_images.htm)
def combine_images(image_path_1, image_path_2, report_name, week):
    #Read the two images
    image1 = Image.open(image_path_1)
    image2 = Image.open(image_path_2)
    
    #resize, first image
    image1 = image1.resize((426, 240))
    image1_size = image1.size
    
    new_image = Image.new('RGB',(2*image1_size[0], image1_size[1]), (250,250,250))
    new_image.paste(image1,(0,0))
    new_image.paste(image2,(image1_size[0],0))
    new_image.save(f"data/plots/report_{report_name}_week_{week}.jpg","JPEG")

## TODO: `save_all_visuals` function to run all of the functions from visuals.py
def save_all_visuals(league, week):
    draft_df = du.get_draft_df(league)

    viz.biggest_steals_chart(week)
    viz.biggest_busts_chart(week)
