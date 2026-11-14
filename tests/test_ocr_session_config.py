import unittest
import threading
import sys
import os
import numpy as np
import inspect
import cv2
import onnxruntime as ort
from rapidocr_onnxruntime import RapidOCR
from pathlib import Path
from unittest.mock import patch
import rapidocr_onnxruntime.utils as util
import core.vision as vision

class OCRSessionTest(unittest.TestCase):
    def setUp(self):
        vision._ocr_engine=None; vision._has_ocr=False; vision.ocr_engine=None; vision.HAS_OCR=False
    def tearDown(self):
        vision._ocr_engine=None; vision._has_ocr=False; vision.ocr_engine=None; vision.HAS_OCR=False
    def test_real_sessions_are_bounded_and_factory_unchanged(self):
        original=util.SessionOptions
        engine, available=vision.init_ocr()
        self.assertTrue(available)
        self.assertIs(util.SessionOptions,original)
        sessions=[engine.text_detector.infer.session,engine.text_cls.infer.session,engine.text_recognizer.session.session]
        for session in sessions:
            opt=session.get_session_options()
            self.assertEqual((opt.intra_op_num_threads,opt.inter_op_num_threads),(2,2))
            self.assertEqual(opt.get_session_config_entry('session.intra_op.allow_spinning'),'0')
            self.assertEqual(opt.get_session_config_entry('session.inter_op.allow_spinning'),'0')
            self.assertEqual(session.get_providers(),['CPUExecutionProvider'])
            self.assertTrue(session._model_path.endswith('.onnx'))
    def test_concurrent_init_reuses_one_engine(self):
        found=[]
        threads=[threading.Thread(target=lambda: found.append(vision.init_ocr())) for _ in range(2)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertTrue(all(ok for _,ok in found))
        self.assertIs(found[0][0],found[1][0])

    def test_original_and_configured_ocr_match_real_fixtures(self):
        original = RapidOCR()
        configured, ok = vision.init_ocr()
        self.assertTrue(ok)
        for filename in ('err_empty.png', 'err_energy.png', 'err_trash.png'):
            image = cv2.imread(str(Path(__file__).resolve().parent.parent / 'assets' / 'templates' / filename))
            self.assertIsNotNone(image)
            old_result, _ = original(image)
            new_result, _ = configured(image)
            self.assertEqual([x[1] for x in old_result or []], [x[1] for x in new_result or []])

    def test_failure_at_each_construction_preserves_original_sessions(self):
        real = ort.InferenceSession
        for failing in (1, 2, 3):
            vision._ocr_engine = None
            calls = []
            def factory(*args, **kwargs):
                calls.append(1)
                if len(calls) == failing:
                    raise RuntimeError('injected failure')
                return real(*args, **kwargs)
            with patch('onnxruntime.InferenceSession', side_effect=factory), patch('core.vision.log_warning') as warning:
                engine, ok = vision.init_ocr()
            self.assertTrue(ok)
            self.assertTrue(warning.called)
            for session in (engine.text_detector.infer.session, engine.text_cls.infer.session, engine.text_recognizer.session.session):
                options = session.get_session_options()
                self.assertEqual((options.intra_op_num_threads, options.inter_op_num_threads), (0, 0))

    def test_unsupported_version_falls_back_and_public_api_works(self):
        with patch('importlib.metadata.version', return_value='unknown'), patch('core.vision.log_warning') as warning:
            engine, ok = vision.init_ocr()
        self.assertTrue(ok)
        self.assertTrue(warning.called)
        self.assertIs(vision.get_ocr_engine(), engine)
        self.assertTrue(vision.has_ocr())
        self.assertEqual(engine.text_detector.infer.session.get_session_options().intra_op_num_threads, 0)

    def test_missing_model_path_uses_unchanged_original(self):
        engine = RapidOCR()
        original_sessions = [engine.text_detector.infer.session, engine.text_cls.infer.session, engine.text_recognizer.session.session]
        original_sessions[0]._model_path = None
        with patch('rapidocr_onnxruntime.RapidOCR', return_value=engine), patch('core.vision.log_warning') as warning:
            found, ok = vision.init_ocr()
        self.assertTrue(ok)
        self.assertTrue(warning.called)
        self.assertEqual([engine.text_detector.infer.session, engine.text_cls.infer.session, engine.text_recognizer.session.session], original_sessions)
        self.assertIs(found, engine)

    def test_candidate_warmup_failure_restores_original_sessions(self):
        engine = RapidOCR()
        original_sessions = [engine.text_detector.infer.session, engine.text_cls.infer.session, engine.text_recognizer.session.session]
        class EngineProxy:
            def __init__(self, wrapped):
                self.text_detector = wrapped.text_detector
                self.text_cls = wrapped.text_cls
                self.text_recognizer = wrapped.text_recognizer
                self.calls = 0
                self.wrapped = wrapped
            def __call__(self, image):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError('candidate warmup failed')
                return self.wrapped(image)
        proxy = EngineProxy(engine)
        with patch('rapidocr_onnxruntime.RapidOCR', return_value=proxy), patch('core.vision.log_warning') as warning:
            found, ok = vision.init_ocr()
        self.assertTrue(ok)
        self.assertTrue(warning.called)
        self.assertIs(found, proxy)
        self.assertEqual(proxy.calls, 2)
        self.assertEqual([engine.text_detector.infer.session, engine.text_cls.infer.session, engine.text_recognizer.session.session], original_sessions)

    def test_assignment_failure_restores_all_original_sessions(self):
        for failing in range(3):
            vision._ocr_engine = None
            engine = RapidOCR()
            inner = [engine.text_detector.infer, engine.text_cls.infer, engine.text_recognizer.session]
            originals = [x.session for x in inner]
            class OwnerProxy:
                def __init__(self, owner, reject):
                    self.owner, self.reject = owner, reject
                @property
                def session(self):
                    return self.owner.session
                @session.setter
                def session(self, value):
                    if self.reject:
                        self.reject = False
                        raise RuntimeError('assignment failure')
                    self.owner.session = value
                def __call__(self, value):
                    return self.owner(value)
            engine.text_detector.infer = OwnerProxy(inner[0], failing == 0)
            engine.text_cls.infer = OwnerProxy(inner[1], failing == 1)
            engine.text_recognizer.session = OwnerProxy(inner[2], failing == 2)
            with patch('rapidocr_onnxruntime.RapidOCR', return_value=engine), patch('core.vision.log_warning') as warning:
                result, ok = vision.init_ocr()
            self.assertTrue(ok)
            self.assertIs(result, engine)
            self.assertTrue(warning.called)
            self.assertEqual([x.session for x in inner], originals)

    def test_public_readers_wait_until_initialization_is_fully_published(self):
        source, first = inspect.getsourcelines(vision.init_ocr)
        target = first + next(i for i, line in enumerate(source) if '_has_ocr = HAS_OCR = True' in line)
        reached = threading.Event()
        resume = threading.Event()
        done = threading.Event()
        reads = []
        def trace(frame, event, arg):
            if frame.f_code is vision.init_ocr.__code__ and event == 'line' and frame.f_lineno == target:
                reached.set()
                if not resume.wait(10):
                    raise TimeoutError('test failed to resume initialization')
            return trace
        def initialize():
            sys.settrace(trace)
            try:
                vision.init_ocr()
            finally:
                sys.settrace(None)
        def read():
            try:
                reads.append((vision.get_ocr_engine(), vision.has_ocr()))
            finally:
                done.set()
        writer = threading.Thread(target=initialize)
        writer.start()
        reader = None
        try:
            self.assertTrue(reached.wait(15), 'initialization did not reach publication')
            reader = threading.Thread(target=read)
            reader.start()
            self.assertFalse(done.wait(.25), 'reader observed partially published OCR state')
        finally:
            resume.set()
            writer.join(15)
            if reader is not None:
                reader.join(15)
        self.assertTrue(done.is_set())
        self.assertIsNotNone(reads[0][0])
        self.assertTrue(reads[0][1])

    def test_explicit_rapidocr_cpu_provider_option_is_preserved(self):
        real = ort.InferenceSession
        with patch('onnxruntime.InferenceSession', wraps=real) as create:
            engine, ok = vision.init_ocr()
        self.assertTrue(ok)
        self.assertEqual(create.call_count, 3)
        for call in create.call_args_list:
            self.assertEqual(call.kwargs['providers'], ['CPUExecutionProvider'])
            self.assertEqual(call.kwargs['provider_options'], [{'arena_extend_strategy': 'kSameAsRequested'}])

    def test_recorded_live_toast_and_energy_full_ocr_output(self):
        fixture = Path(os.environ.get('TEMP', '')) / 'codex_existing_frames_20261113' / '00092.jpg'
        if not fixture.is_file():
            self.skipTest('recorded live frame unavailable')
        frame = cv2.imread(str(fixture))
        self.assertIsNotNone(frame)
        h, w = frame.shape[:2]
        original = RapidOCR()
        configured, ok = vision.init_ocr()
        self.assertTrue(ok)
        for image in (frame[:int(h*.22), int(w*.4):int(w*.65)], frame[int(h*.48):int(h*.8), int(w*.1):int(w*.8)]):
            before, _ = original(image)
            after, _ = configured(image)
            self.assertEqual(len(before or []), len(after or []))
            for first, second in zip(before or [], after or []):
                self.assertEqual(first[1], second[1])
                np.testing.assert_allclose(first[0], second[0], atol=0.01)
                self.assertAlmostEqual(float(first[2]), float(second[2]), delta=1e-4)

if __name__=='__main__':unittest.main()
