#version 440
layout(location=0) in vec2 qt_TexCoord0;
layout(location=0) out vec4 fragColor;
layout(std140,binding=0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 size;
    float cornerRadius;
    float depth;
};
float box(vec2 p,vec2 b,float r) {
    vec2 q=abs(p)-b+vec2(r);
    return length(max(q,vec2(0)))+min(max(q.x,q.y),0.0)-r;
}
// Gaussian half-plane coverage. CSS blur has sigma = blur-radius / 2.
float coverage(float distance,float sigma) {
    float x=distance/(sigma*1.41421356237);
    float t=1.0/(1.0+0.3275911*abs(x));
    float erf=1.0-(((((1.061405429*t-1.453152027)*t)+1.421413741)*t-0.284496736)*t+0.254829592)*t*exp(-x*x);
    return 0.5*(1.0+sign(x)*erf);
}
void main() {
    vec2 p=qt_TexCoord0*size-size*.5;
    vec2 b=size*.5;
    float radius=min(cornerRadius,min(b.x,b.y));
    float d=box(p,b,radius);
    float mask=1.0-smoothstep(-1.,0.,d);
    bool strong=depth>4.0;
    float dark=.72*coverage(box(p-vec2(depth),b,radius),strong?5.5:3.5);
    float light=(strong?.11:.10)*coverage(box(p+vec2(strong?4.:3.),b,radius),strong?4.5:3.);
    // CSS lists the dark shadow first: it is composited over the light one.
    vec3 color=mix(mix(vec3(20./255.),vec3(75./255.),light),vec3(0.),dark);
    fragColor=vec4(color*mask,mask)*qt_Opacity;
}
