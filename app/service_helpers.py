#Buckaroo Project - June 1, 2025
#This file helps deliver on services the server provides

import re


def clean_table_name(csv_name):
    """
    Cleans the file name so that it is ready to be used to make a table in the database, it needs to:
    - Remove file extension (.csv)
    - Replace spaces/special chars with underscores
    - Ensure it starts with a letter (SQL requirement)
    :param csv_name: csv name from user upload
    :return: cleaned name without
    """
    removed_extension = csv_name[0:len(csv_name)-4]
    clean_name = re.sub(r'[^a-zA-Z0-9_]', '_', removed_extension)
    if not clean_name[0].isalpha():
        clean_name = 'table' + clean_name
    return clean_name.lower()