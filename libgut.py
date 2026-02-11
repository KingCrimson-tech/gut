import argparse
import configparser
from datetime import datetime
import grp, pwd
from fnmatch import fnmatch
import hashlib
from math import ceil
import re
import sys
import zlib
import os


# main argument parser
argparser = argparse.ArgumentParser(description="Content Tracker")

# sub argument parser (init, commit)
argsubparsers = argparser.add_subparsers(
    title="Commands", dest="command"
)  # dest="command" means that the sub argument is passed as a string in command
argsubparsers.required = True


# the passed sub arguments are then used to call the bridge functions / the actual functionalities
def main(argv=sys.argv[1:]):
    args = argparser.parse_args(argv)
    match args.command:
        case "add":
            cmd_add(args)
        case "cat-file":
            cmd_cat_file(args)
        case "check-ignore":
            cmd_check_ignore(args)
        case "commit":
            cmd_commit(args)
        case "hash-object":
            cmd_hash_object(args)
        case "init":
            cmd_init(args)
        case "log":
            cmd_log(args)
        case "ls-files":
            cmd_ls_files(args)
        case "ls-tree":
            cmd_ls_tree(args)
        case "rev-parse":
            cmd_rev_parse(args)
        case "rm":
            cmd_rm(args)
        case "show-ref":
            cmd_show_ref(args)
        case "status":
            cmd_status(args)
        case "tag":
            cmd_tag(args)
        case _:
            print("Bad command.")


class GitRepository(object):
    # a repo has a worktree showing the file structure and a subtree called git sub directory to store the metadata
    worktree = None
    gitdir = None
    conf = None

    def __init__(self, path, force=False):
        self.worktree = path
        self.gitdir = os.path.join(path, ".git")

        if not (force or os.path.isdir(self.gitdir)):
            raise Exception(f"Not a Git repository {path}")

        # read config file in .git/config
        self.conf = configparser.ConfigParser()
        cf = repo_file(self, "config")

        if cf and os.path.exists(cf):
            self.conf.read([cf])
        elif not force:
            raise Exception("Configuration file missing")

        if not force:
            vers = int(self.conf.get("core", "repositoryformatversion"))
            if vers != 0:
                raise Exception("Unsupported repositoryformatversion: {vers}")


# utility funcs
def repo_path(repo, *path):
    return os.path.join(repo.gitdir, *path)  # this computes path under gitdir


# same as repo_path, but create dirname(*path) if absent
def repo_file(repo, *path, mkdir=False):
    if repo_dir(repo, *path[:-1], mkdir=mkdir):
        return repo_path(repo, *path)


# same as repo_path, but mkdir *path if absent if mkdir
def repo_dir(repo, *path, mkdir=False):
    path = repo_path(repo, *path)
    if os.path.exists(path):
        if os.path.isdir(path):
            return path
        else:
            raise Exception(f"Not a directory {path}")

    if mkdir:
        os.makedirs(path)
        return path
    else:
        return None

def repo_create(path):
    repo = GitRepository(path, True)

    #check if path doesnt exist or empty
    if os.path.exists(repo.worktree):
        if not os.path.isdir(repo.worktree):
            raise Exception(f"{path} is not a directory")
        if os.path.exists(repo.gitdir) and os.listdir(repo.gitdir):
            raise Exception(f"{path} is not empty!")    
    
    else:
        os.makedirs(repo.worktree)
    
    assert repo_dir(repo, "branches", mkdir=True)
    assert repo_dir(repo, "objects", mkdir=True)
    assert repo_dir(repo, "refs", "tags", mkdir=True)
    assert repo_dir(repo, "refs", "heads", mkdir=True)

    #.git/description
    with open(repo_file(repo, "description"), "w") as f:
        f.write("Unnamed repository: edit this file 'description to name the repository.\n")
    
    #.git/HEAD
    with open(repo_file(repo, "HEAD"), "w") as f:
        f.write("ref: refs/heads/master\n")

    with open(repo_file(repo, "config"), "w") as f:
        config = repo_default_config()
        config.write(f)
    
    return repo

#INI-format config file details for the gitdir(the three fields include repoformatversion, filemode(tracking file nodes) and bare(worktree indicator))
def repo_default_config():
    ret = configparser.ConfigParser()

    ret.add_section("core")
    ret.set("core", "repositoryformatversion", "0")
    ret.set("core", "filemode", "false")
    ret.set("core", "bare", "false")

    return ret

#the repo creation is done now it is the init cmd
argsp = argsubparsers.add_parser("init", help="Initialize a new, empty repository.")
argsp.add_argument("path", metavar="directory", nargs="?", default=".", help="Where to create the repository.")

def cmd_init(args):
    repo_create(args.path)


#this function helps us to find the main root directory that the other git commands will be working on and it does it by looking recursively for the .git directory
def repo_find(path=".", required=True):
    path = os.path.realpath(path)

    #found
    if os.path.isdir(os.path.join(path, ".git")):
        return GitRepository(path)
    
    #a recursion base
    parent = os.path.realpath(os.path.join(path, ".."))

    if parent == path:
        if required:
            raise Exception("No git directory")
        else:
            return None
    
    #recursive case
    return repo_find(parent, required)

''''Reading and writing objects'''
#In git unlike typical file systems, it is a content addresses filesystem, meaning it derives its file name from the content of the file and also if the content is changed then a new file itself is created and thus a git object is just that the the file in the repo with its path determined by the contents

#an object in git is represnted in a particular fashion

'''
type(blob, commit, tag or tree), ASCII space, size of obj in ascii number, null then contents of the obj
ex:
00000000  63 6f 6d 6d 69 74 20 31  30 38 36 00 74 72 65 65  |commit 1086.tree|
'''

#a generic object
class GitObject(object):

    def __init__(self, data=None):
        if data != None:
            self.deserialize(data)
        else:
            self.init()
    
    def serialize(self, repo):
        #this function will be implenmented by subclasses coz there are diff objs

        raise Exception("Todo")

    def deserialize(self, data):
        raise Exception("Todo")
    
    def init(self):
        pass 

#reading files, it requires to know its SHA-1 hash and then path is computed as : first 2 characters / rest characters as file name decompressed by zlib

def object_read(repo, sha):
    #read the sha from git repository repo and retuen a GitObject 
    path = repo_file(repo, "objects", sha[0:2], sha[2:])

    if not os.path.isfile(path):
        return None
    
    with open(path, "rb") as f:
        raw = zlib.decompress(f.read())

        #read object type
        x = raw.find(b' ')
        fmt = raw[0:x]

        #read and validate object size
        y = raw.find(b'\x00', x)
        size = int(raw[x:y].decode("ascii"))
        if size != len(raw) - y - 1:
            raise Exception(f"malformed object {sha}: bad length")
        
        #picking constructor
        match fmt:
            case b'commit': c=GitCommit
            case b'tree': c=GitTree
            case b'tag' : c=GitTag
            case b'blob': c=GitBlob
            case _:
                raise Exception(f"unknown type {fmt.decode("ascii")} for object {sha}")
            
        return c(raw[y+1:])