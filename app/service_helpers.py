#Buckaroo Project - June 1, 2025
#This file helps deliver on services the server provides

import re


def clean_table_name(csv_name):
    removed_extension = csv_name[0:len(csv_name)-4]
    clean_name = re.sub(r'[^a-zA-Z0-9_]', '_', removed_extension)
    if not clean_name[0].isalpha():
        clean_name = 'table_' + clean_name
    return clean_name