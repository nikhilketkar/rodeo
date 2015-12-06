# start compatibility with IPython Jupyter 4.0+
try:
    from jupyter_client import BlockingKernelClient
except ImportError:
    from IPython.kernel import BlockingKernelClient

# python3/python2 nonsense
try:
    from Queue import Empty
except:
    from queue import Empty

import atexit
import subprocess
import uuid
import time
import os
import sys
import json

__dirname = os.path.dirname(os.path.abspath(__file__))

vars_patch = """
import json
try:
    import pandas as pd
except:
    pd = None

def __get_variables():
    if not pd:
        print('[]')
    variable_names = globals().keys()
    data_frames = []
    for v in variable_names:
        if v.startswith("_"):
            continue
        if isinstance(globals()[v], pd.DataFrame):
            data_frames.append({
                "name": v,
                "dtype": "DataFrame"
            })
    print(json.dumps(data_frames))

"""

class Kernel(object):
    def __init__(self, active_dir, pyspark):
        # kernel config is stored in a dot file with the active directory
        config = os.path.join(active_dir, ".kernel-%s.json" % str(uuid.uuid4()))
        # right now we're spawning a child process for IPython. we can
        # probably work directly with the IPython kernel API, but the docs
        # don't really explain how to do it.
        log_file = None
        if pyspark:
            os.environ["IPYTHON_OPTS"] = "kernel -f %s" % config
            pyspark = os.path.join(os.environ.get("SPARK_HOME"), "bin/pyspark")
            spark_log = os.environ.get("SPARK_LOG", None)
            if spark_log:
                log_file = open(spark_log, "w")
            spark_opts = os.environ.get("SPARK_OPTS", "")
            args = [pyspark] + spark_opts.split()  # $SPARK_HOME/bin/pyspark <SPARK_OPTS>
            p = subprocess.Popen(args, stdout=log_file, stderr=log_file)
        else:
            args = [sys.executable, '-m', 'IPython', 'kernel', '-f', config]
            p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # when __this__ process exits, we're going to remove the ipython config
        # file and kill the ipython subprocess
        atexit.register(p.terminate)

        def remove_config():
            if os.path.isfile(config):
                os.remove(config)
        atexit.register(remove_config)

        # i found that if i tried to connect to the kernel immediately, so we'll
        # wait until the config file exists before moving on
        while os.path.isfile(config)==False:
            time.sleep(0.1)

        def close_file():
            if log_file:
                log_file.close()
        atexit.register(close_file)

        # fire up the kernel with the appropriate config
        self.client = BlockingKernelClient(connection_file=config)
        self.client.load_connection_file()
        self.client.start_channels()
        # load our monkeypatches...
        self.execute("%matplotlib inline")
        self.execute(vars_patch)

    def _run_code(self, code, timeout=0.1):
        # this function executes some code and waits for it to completely finish
        # before returning. i don't think that this is neccessarily the best
        # way to do this, but the IPython documentation isn't very helpful for
        # this particular topic.
        #
        # 1) execute code and grab the ID for that execution thread
        # 2) look for messages coming from the "iopub" channel (this is just a
        #    stream of output)
        # 3) when we get a message that is one of the following, save relevant
        # data to `data`:
        #       - execute_result - content from repr
        #       - stream - content from stdout
        #       - error - ansii encoded stacktrace
        # the final piece is that we check for when the message indicates that
        # the kernel is idle and the message's parent is the original execution
        # ID (msg_id) that's associated with our executing code. if this is the
        # case, we'll return the data and the msg_id and exit
        msg_id = self.client.execute(code)
        output = { "msg_id": msg_id, "output": None, "image": None, "error": None }
        while True:
            try:
                reply = self.client.get_iopub_msg(timeout=timeout)
            except Empty:
                continue

            if "execution_state" in reply['content']:
                if reply['content']['execution_state']=="idle" and reply['parent_header']['msg_id']==msg_id:
                    if reply['parent_header']['msg_type']=="execute_request":
                        return output
            elif reply['header']['msg_type']=="execute_result":
                output['output'] = reply['content']['data'].get('text/plain', '')
            elif reply['header']['msg_type']=="display_data":
                output['image'] = reply['content']['data'].get('image/png', '')
            elif reply['header']['msg_type']=="stream":
                output['output'] = reply['content'].get('text', '')
            elif reply['header']['msg_type']=="error":
                output['error'] = "\n".join(reply['content']['traceback'])

    def execute(self, code):
        return self._run_code(code)

    def complete(self, code, timeout=0.1):
        # Call ipython kernel complete, wait for response with the correct msg_id,
        # and construct appropriate UI payload.
        # See below for an example response from ipython kernel completion for 'el'
        #
        # {
        # 'parent_header':
        #     {u'username': u'ubuntu', u'version': u'5.0', u'msg_type': u'complete_request',
        #     u'msg_id': u'5222d158-ada8-474e-88d8-8907eb7cc74c', u'session': u'cda4a03d-a8a1-4e6c-acd0-de62d169772e',
        #     u'date': datetime.datetime(2015, 5, 7, 15, 25, 8, 796886)},
        # 'msg_type': u'complete_reply',
        # 'msg_id': u'a3a957d6-5865-4c6f-a0b2-9aa8da718b0d',
        # 'content':
        #     {u'matches': [u'elif', u'else'], u'status': u'ok', u'cursor_start': 0, u'cursor_end': 2, u'metadata': {}},
        # 'header':
        #     {u'username': u'ubuntu', u'version': u'5.0', u'msg_type': u'complete_reply',
        #     u'msg_id': u'a3a957d6-5865-4c6f-a0b2-9aa8da718b0d', u'session': u'f1491112-7234-4782-8601-b4fb2697a2f6',
        #     u'date': datetime.datetime(2015, 5, 7, 15, 25, 8, 803470)},
        # 'buffers': [],
        # 'metadata': {}
        # }
        #
        msg_id = self.client.complete(code)
        output = { "msg_id": msg_id, "output": None, "image": None, "error": None }
        while True:
            try:
                reply = self.client.get_shell_msg(timeout=timeout)
            except Empty:
                continue

            if "matches" in reply['content'] and reply['msg_type']=="complete_reply" and reply['parent_header']['msg_id']==msg_id:
                results = []
                for completion in reply['content']['matches']:
                    result = {
                        "value": completion,
                        "dtype": "---"
                    }
                    if "." in code:
                        result['text'] = ".".join(result['value'].split(".")[1:])
                        result["dtype"] = "function"
                    else:
                        # result['text'] = result['value'].replace(code, '', 1)
                        result['text'] = result['value']
                        result["dtype"] = "session variable" # type(globals().get(code)).__name__
                    results.append(result)
                jsonresults = json.dumps(results)
                output['output'] = jsonresults
                return output
            #else:
                #Don't know what to do with the rest.
                #I've observed parent_header msg_types: kernel_info_request, execute_request
                #Just discard for now

    def get_dataframes(self):
        return self.execute("__get_variables()")
