import os

from manim import LEFT, RIGHT, Arrow, Create, FadeIn, Rectangle, Scene, Text, VGroup

DURATION = float(os.environ.get("SCENE_DURATION", "4"))


class Intro(Scene):
    def construct(self):
        self.play(FadeIn(Text("Queue", font_size=48)), run_time=1)
        self.wait(max(0.0, DURATION - 1))


class Flow(Scene):
    def construct(self):
        queue = VGroup(Rectangle(width=2.5, height=1), Text("queue", font_size=28))
        worker = VGroup(Rectangle(width=2.5, height=1), Text("worker", font_size=28))
        queue.shift(3 * LEFT)
        worker.shift(3 * RIGHT)
        self.play(Create(queue), Create(worker), run_time=1)
        self.play(Create(Arrow(queue.get_right(), worker.get_left())), run_time=1)
        self.wait(max(0.0, DURATION - 2))
