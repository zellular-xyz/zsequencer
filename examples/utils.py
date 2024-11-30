def deep_merge(dict1, dict2):
    """
    Deeply merges two dictionaries where dict2 overwrites dict1 in overlapping keys.
    """
    for key, value in dict2.items():
        if isinstance(value, dict) and key in dict1 and isinstance(dict1[key], dict):
            dict1[key] = deep_merge(dict1[key], value)  # Merge nested dictionaries recursively
        else:
            dict1[key] = value  # Overwrite or add key from dict2

    return dict1
