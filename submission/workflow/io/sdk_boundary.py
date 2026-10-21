from http.client import IncompleteRead

from nova_sdk import Client, NovaError


def sdk_call(call, **payload):
    """Normalize only SDK I/O and its non-object HTTP error envelope defect."""
    try:
        return call(**payload)
    except (TimeoutError, OSError, IncompleteRead) as error:
        raise NovaError('API_UNAVAILABLE') from error
    except AttributeError as error:
        trace = error.__traceback__
        while trace:
            frame = trace.tb_frame
            if (frame.f_code is Client._request.__code__ and 'error' in frame.f_locals
                    and not isinstance(frame.f_locals['error'], dict)):
                raise NovaError('INVALID_API_RESPONSE') from error
            trace = trace.tb_next
        raise
