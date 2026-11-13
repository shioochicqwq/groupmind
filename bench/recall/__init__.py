"""Idea 3 (human-like memory): how the members of a group recall, mined from the group's own chat.

markers     cheap surface patterns that pick candidate messages (high recall, low precision)
run_label   a model labels each candidate in context: is it a recall, of what, in what form
run_link    for recalls of earlier group chat, find the original and compare (lag, role, fidelity)
"""
